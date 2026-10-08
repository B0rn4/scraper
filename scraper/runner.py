"""Glavni tok: dohvat, filter, obavijesti, izvještaji, nadzor izvora."""

import dataclasses
import html
import json
import re
import sqlite3
import subprocess
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from . import dedupe, planwatch, report, risks, tenders, watch
from .ispu import APPROX_RADIUS_M, Ispu, check_land, gp_text, heritage_warning
from .plans import Plans
from .prices import MAX_AGE_DAYS, PPV_YEAR, AskingPrices, Ppv, land_note, land_short, place_of
from .db import State
from .filters import effective_price, evaluate
from .http import Http, blocked
from .locations import Locator
from .models import HOUSE, LAND, PASS, REJECT, WARN, Decision, Listing
from .notify import (DISLIKE, MUTE_PREFIX, SOURCE_LABELS, UNMUTE_PREFIX, Email, Telegram, health_label, muted_markup,
                     safe_url, summary_text, unmuted_markup)
from .sources import ALL
from .sources.base import FULL, INCREMENTAL
from .text import fmt_eur, fold, plural

ROOT = Path(__file__).resolve().parent.parent
LAND_CHECK_SECONDS = 120   # najdulje trajanje provjera građevinskog područja po pokretanju
TENDER_CHECK_SECONDS = 240  # isto za čestice iz natječaja (jednom dnevno)
PLAN_CHECK_SECONDS = 180    # najdulje čitanje odluka o planovima za tjedni izvještaj
PLAN_PAGE_SECONDS = 20      # najdulje čekanje jedne stranice (sn.pgz.hr, zavod.pgz.hr)
RESERVE_MINUTES = 30        # GitHubov raspored radi samo kad cron-job.org kasni ovoliko
UNSENT_DAYS = 7             # neposlana obavijest (Telegram ne radi) čeka najviše toliko
PRUNE_DAYS = 30             # odbijeni oglas izvan našeg područja ostaje u bazi toliko dana nakon zadnjeg viđenja
DETAIL_ALERT_RUNS = 9       # stranice oglasa (captcha ili greška) toliko pokretanja zaredom (3 sata) → upozorenje
MAIN_TRIGGER_ALERT = timedelta(hours=2)   # cron-job.org toliko ne pokreće GitHub (radi samo rezerva) → upozorenje
CLOCK_TOLERANCE = timedelta(minutes=10)   # sat na Redmiju smije toliko odstupati
LISTING_ERROR_RUNS = 3      # isti izvor toliko pokretanja zaredom ima oglase koji se ne daju obraditi → upozorenje
DEEP_ALERT_DAYS = 3         # dnevno dublje čitanje toliko dana zaredom ne uspijeva → upozorenje
CODE_ALERT_RUNS = 18        # Redmi toliko GitHubovih pokretanja (~6 sati) radi s drukčijim kodom → upozorenje
# Izvor radi, ali ovoliko dana nema nijedan nov oglas (npr. portal ne poštuje redoslijed "najnoviji"):
# upozorenje. Stvarni tempo (listopad 2026.): Njuškalo 375–1245 dnevno, index 21–103, oglasnik 6–31
# (noćni uvoz agencija oko 5 h), nekretnine.hr 4–28, realestatecroatia 8–14 (također ujutro), burza
# nekoliko. Noć (8–9 sati bez čitanja) Njuškalu ne smije biti dovoljna za upozorenje.
NEW_LISTING_DAYS = {"njuskalo": 0.5, "index_oglasi": 2, "nekretnine_hr": 3, "oglasnik": 3,
                    "realestatecroatia": 3, "burza": 5}


def load_config(path: Path = ROOT / "config.yaml") -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


class Runner:
    def __init__(self, db_path: Path, out_dir: Path, send: bool = True, only: list[str] | None = None,
                 device: str = "github", redmi_db: Path | None = None, seen_file: Path | None = None,
                 prices_file: Path | None = None):
        self.cfg = load_config()
        self.tz = ZoneInfo(self.cfg["vrijeme"]["zona"])
        self.now = datetime.now(self.tz)
        self.stamp = self.now.isoformat(timespec="seconds")
        self.db_path = db_path
        self.out_dir = out_dir
        self.only = only
        self.device = device          # "github" ili "redmi": koji izvori se ovdje čitaju
        self.redmi_db = redmi_db      # stanje s Redmija (na GitHubu: nadzor i tjedni izvještaj)
        self.seen_file = seen_file    # na Redmiju: sažetak već viđenih oglasa s GitHuba
        self.prices_file = prices_file  # na Redmiju: medijani traženih cijena s GitHuba
        self.locator = Locator()
        self.ppv = Ppv(self.locator)
        self.plans = Plans()
        self._ispu = None               # ISPU (građevinsko područje), otvara se kad zatreba
        self._place_names = {fold(n): n for j in self.locator.jls.values() for n in [j.name, *j.settlements]}
        self.criteria = self.cfg["kriteriji"]
        self.http = Http()
        notif = self.cfg.get("obavijesti", {})
        self.wants_telegram = send and notif.get("telegram", True)    # trebao bi slati (provjera postavki)
        self.telegram = Telegram.from_env() if self.wants_telegram else None
        self.email = Email.from_env() if send and notif.get("email", True) else None
        # Mail se očekuje samo na GitHubu (Redmi šalje na Telegram, GitHub javlja i za njega).
        self.wants_email = send and notif.get("email", True) and device == "github"
        self.skew = timedelta(0)        # na Redmiju: koliko njegov sat žuri (izmjereno pri preuzimanju)
        self.log_lines: list[str] = []
        self.muted: set[str] = set()   # "Ne zanima me" (gumb ispod poruke)
        self._redmi_ok: bool | None = None
        self._prev_unsent: list = []           # neposlane obavijesti iz prošlih pokretanja
        self._unsent_since: dict[str, str] = {}

    # --- pomoćno ---

    def log(self, msg: str) -> None:
        line = f"[{datetime.now(self.tz):%H:%M:%S}] {msg}"
        print(line, flush=True)
        self.log_lines.append(line)

    def enabled_sources(self):
        """Izvori za ovaj uređaj: true = GitHub, "redmi" = Redmi (kućna IP adresa)."""
        for name, where in self.cfg["izvori"].items():
            if not where or (self.only and name not in self.only):
                continue
            if (where is True and self.device == "github") or where == self.device:
                yield ALL[name](self.http, self.locator, self.criteria)

    def _redmi_usable(self) -> bool:
        """Postoji li čitljivo stanje s Redmija. Oštećena datoteka ne smije zaustaviti
        pokretanje (portali, natječaji); javlja se kao kvar Redmija (_check_redmi)."""
        if self._redmi_ok is None:
            self._redmi_ok = False
            if self.redmi_db and Path(self.redmi_db).exists():
                try:
                    other = State(self.redmi_db)
                    self._redmi_ok = other.conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
                    other.close()
                except sqlite3.DatabaseError as exc:
                    self.log(f"Stanje s Redmija nije čitljivo: {exc}")
                if not self._redmi_ok:
                    self.log("Stanje s Redmija je oštećeno – preskače se")
        return self._redmi_ok

    def in_active_hours(self) -> bool:
        v = self.cfg["vrijeme"]
        return v["od_sata"] <= self.now.hour < v["do_sata"]

    def _email(self, subject: str, text: str, html_body: str = "", attachments=()) -> bool:
        """False samo kad slanje nije uspjelo (bez postavki za mail nema se što ponoviti)."""
        if not self.email:
            self.log(f"(mail nije poslan – nema postavki) {subject}")
            return True
        try:
            self.email.send(subject, text, html_body, list(attachments))
            return True
        except Exception as exc:  # noqa: BLE001
            self.log(f"Slanje maila nije uspjelo: {exc}")
            return False

    def _report(self, name: str, title: str, entries: list[dict], sources: list[dict], note: str = "") -> Path:
        path = self.out_dir / f"{name}-{self.now:%Y-%m-%d-%H%M}.html"
        report.write(path, entries, title, f"{self.now:%d.%m.%Y. %H:%M}", sources, note)
        self.log(f"Izvještaj: {path} ({len(entries)} oglasa)")
        return path

    def _send_report(self, path: Path, caption: str, subject: str, mail: bool = False) -> bool:
        """Izvještaj ide na Telegram; mail samo ako je izričito traženo (mail je za
        tjedni izvještaj i greške). False kad slanje na Telegram nije uspjelo."""
        ok = True
        if self.telegram:
            try:
                self.telegram.send_document(path, caption)
            except Exception as exc:  # noqa: BLE001
                self.log(f"Slanje izvještaja na Telegram nije uspjelo: {exc}")
                ok = False
        if mail:
            self._email(subject, caption.replace("<b>", "").replace("</b>", ""), attachments=[path])
        return ok

    # --- naredbe ---

    def run(self, force: bool = False, reserve: bool = False) -> None:
        """Redovno pokretanje (svakih 20 minuta). reserve: GitHubov raspored (rezerva za
        cron-job.org) – radi samo ako je zadnje pokretanje starije od RESERVE_MINUTES, inače
        bi se mogao poklopiti s Redmijem (isti oglas dvaput)."""
        if not force and not self.in_active_hours():
            self.log(f"Izvan radnog vremena ({self.now:%H:%M}), ništa se ne radi.")
            return
        state = State(self.db_path)
        if not state.meta_get("popravak:tiho_odbijeni"):
            # Jednokratno: odbijeni oglasi zabilježeni "tiho" smatrali su se viđenima, pa ni
            # oni ni njihove kopije na drugim portalima nisu stizali kad počnu odgovarati.
            n = state.conn.execute("UPDATE listings SET notified_at = NULL, notified_price = NULL "
                                   "WHERE notified_at LIKE 'tiho:%' AND status = ?", (REJECT,)).rowcount
            state.meta_set("popravak:tiho_odbijeni", self.stamp)
            state.conn.commit()
            self.log(f"Tiho zabilježeni odbijeni oglasi više se ne smatraju viđenima: {n}")
        # Rezerva se uspoređuje sa zadnjim pokretanjem glavnog okidača, ne sa svojim: inače bi za
        # ispada cron-job.org radila svakih 40 umjesto 20 minuta.
        if not state.meta_get("popravak:tiho_duplikati"):
            self._repair_silent_twins(state)
        last = state.meta_get("glavni_okidac") or state.meta_get("last_run")
        if reserve and last and self._age(last) is not None and self._age(last) < timedelta(minutes=RESERVE_MINUTES):
            self.log(f"Rezervno pokretanje: glavni okidač radi (zadnje pokretanje {last[11:16]}), ništa se ne radi.")
            state.close()
            return
        if not reserve:
            state.meta_set("glavni_okidac", self.stamp)
        self._main_trigger(state, reserve)
        self._heartbeat(state)
        self._mail_health(state)
        try:
            self._prune(state)
        except Exception as exc:  # noqa: BLE001 – čišćenje (npr. pun disk kod VACUUM) ne smije zaustaviti pokretanje
            self.log(f"Čišćenje baze: GREŠKA {type(exc).__name__}: {exc}")
        self._read_feedback(state)
        self.muted = state.muted(self._github_info().get("utisani"))
        self._prev_unsent = self._load_unsent(state)
        seen = self._load_seen(state)
        prices = self._load_prices(state)
        to_notify: list[tuple[Listing, Decision, str]] = []
        baseline: list[tuple[object, list[tuple[Listing, Decision]], str]] = []
        today = self.now.date().isoformat()
        try:
            for src in self.enabled_sources():
                if src.daily and state.meta_get(f"daily:{src.name}") == today:
                    continue
                first = state.meta_get(f"baseline:{src.name}") is None
                mode = FULL if first else INCREMENTAL
                # Prošlo čitanje nije stiglo do oglasa od pretprošlog (Njuškalo: najviše stranica):
                # čita se od istog trenutka, dublje, dok se praznina ne zatvori.
                gap = state.meta_get(f"od:{src.name}") or ""
                src.since = gap or next((h["last_ok"] for h in state.health_all() if h["source"] == src.name), None)
                src.catch_up = bool(gap)
                src.known_prices = state.known_prices(src.name)
                # Jednom dnevno, poslijepodne (jutarnje pokretanje već ima dnevne provjere).
                src.deep = (getattr(src, "deep_daily", False) and not first and self.now.hour >= 12
                            and state.meta_get(f"dubinsko:{src.name}") != today)
                try:     # dublje čitanje koje nije stiglo do kraja nastavlja se gdje je stalo
                    src.deep_from = json.loads(state.meta_get(f"dubinsko_str:{src.name}") or "{}")
                except ValueError:
                    src.deep_from = {}
                src.pending = [] if first else self._load_pending(state, src.name)
                src.captcha_until = state.meta_get(f"stanka:{src.name}") or ""   # nakon captche (Njuškalo)
                self.log(f"{src.label}: dohvat ({'početni, cijelo područje' if first else 'najnoviji'})")
                try:
                    listings = src.fetch(mode, state.known_ids(src.name))
                    if not listings and src.name != "fina":
                        raise RuntimeError("izvor nije vratio nijedan oglas (moguća promjena stranice)")
                except Exception as exc:  # noqa: BLE001
                    self._source_failed(state, src, exc)
                    continue
                # Oglasi koji se prošli put nisu dali obraditi: ponovno, i kad ih izvor ovaj put nije
                # pročitao (index, nekretnine… ne čitaju odgođene; oglas je mogao pasti na 3. stranicu).
                have = {x.key for x in listings} | {x.key for x in getattr(src, "deferred", [])}
                listings = listings + [p for p in src.pending if p.extra.get("greska_obrade")
                                       and p.key not in have and not state.get(p.key)]
                decided, errors, failed = [], [], []
                silent_baseline = first and not getattr(src, "baseline_report", True)
                if not state.conn.in_transaction:
                    state.conn.execute("BEGIN")
                for x in listings:
                    # Jedan neispravan oglas (promijenjeno polje na portalu, greška u programu) ne ruši
                    # pokretanje, a od njega se ništa ne zapisuje (ni nova cijena): sljedeći put se
                    # obrađuje ponovno, kao da ga ovo pokretanje nije vidjelo.
                    done = len(decided)
                    state.conn.execute("SAVEPOINT oglas")
                    try:
                        prev = state.get(x.key)
                        if prev:  # podaci sa stranice oglasa iz ranijeg dohvata (popis ih nema)
                            # Površina iz kratkog isječka ili naslova (burza, Njuškalo zemljište) ne
                            # prepisuje onu sa stranice oglasa.
                            if prev.get("area") and (not x.area or x.extra.get("povrsina_iz_teksta")):
                                x.area = prev["area"]
                            if not x.settlement and prev.get("settlement"):
                                x.settlement = prev["settlement"]
                                x.location_text = x.location_text or x.settlement
                        partial = x.extra.get("opis_skracen") or x.extra.get("samo_popis")
                        if prev and partial and "spominje parcelaciju" in (prev.get("reasons") or ""):
                            x.extra["parcelacija_ranije"] = True     # opis je bio na stranici oglasa
                        d = evaluate(x, self.criteria, self.locator, prices)
                        if prev and prev.get("category") and "kategorija" not in x.extra:
                            x.extra["kategorija"] = prev["category"]   # iz opisa ranijeg dohvata
                        if prev and d.notify and partial and prev.get("status") == REJECT:
                            d = self._keep_text_reject(d, prev, effective_price(
                                x.price, x.area, bool(x.extra.get("ukupna_cijena")), x.kind) is None)
                        old = state.upsert(x, d, self.stamp)
                        decided.append((x, d))
                        if silent_baseline or (old is None and x.extra.get("stari_oglas")):
                            # Bez obavijesti (početak praćenja ili stari oglas ponovno objavljen),
                            # ali zabilježeno – sniženje cijene kasnije i dalje stiže. Odbijeni se ne
                            # bilježe: kad počne odgovarati (izmjena oglasa ili pravila), stiže poruka.
                            if d.notify:
                                state.mark_notified(x.key, x.price, f"tiho:{self.stamp}")
                            continue
                        if not first:
                            headline = self._notify_reason(x, d, old)
                            if headline is not None and self._is_muted(state, seen, x, d, old):
                                headline = None
                            if headline is not None:
                                headline = self._check_seen(state, seen, x, d, old, headline)
                            if headline is not None:
                                self._enrich(x, d, prices)
                                to_notify.append((x, d, headline))
                    except Exception as exc:  # noqa: BLE001
                        state.conn.execute("ROLLBACK TO oglas")
                        del decided[done:]
                        errors.append(f"{x.key}: {type(exc).__name__}: {exc}")
                        failed.append(x)
                        traceback.print_exc()
                    finally:
                        state.conn.execute("RELEASE oglas")
                # Odgođeni (stranica oglasa) i neobrađeni oglasi čekaju sljedeće pokretanje i kad ih
                # popis više nema; neobrađeni najviše LISTING_ERROR_RUNS puta (zatim upozorenje).
                deferred = list(getattr(src, "deferred", []))
                for x in failed:
                    x.extra["greska_obrade"] = x.extra.get("greska_obrade", 0) + 1
                    if x.extra["greska_obrade"] < LISTING_ERROR_RUNS:
                        deferred.append(x)
                if deferred or src.pending:
                    self.log(f"{src.label}: odgođeno za sljedeće pokretanje {len(deferred)} oglasa")
                    state.meta_set(f"odgodjeno:{src.name}", json.dumps([x.to_dict() for x in deferred], ensure_ascii=False))
                if errors and len(errors) * 2 >= len(listings):
                    state.conn.commit()
                    self._source_failed(state, src, RuntimeError(
                        f"{len(errors)} od {len(listings)} oglasa nije obrađeno (promjena stranice?) – {errors[0]}"))
                    # Obrađeni oglasi su zapisani (i nova cijena): njihove obavijesti čekaju u redu.
                    self._remember_unsent(state, self._prev_unsent + to_notify)
                    continue
                if errors:
                    self.log(f"{src.label}: preskočeno zbog greške {len(errors)} oglasa – {errors[0]}")
                self._source_ok(state, src)
                self._listing_errors(state, src, errors, failed)
                self._detail_health(state, src)
                self._read_gap(state, src)
                self._fresh_health(state, src)
                counts = {s: sum(1 for _, d in decided if d.status == s) for s in (PASS, WARN, REJECT)}
                self.log(f"{src.label}: {len(listings)} oglasa – ✅ {counts[PASS]}, ⚠ {counts[WARN]}, ❌ {counts[REJECT]}")
                if first:
                    if not silent_baseline:
                        baseline.append((src, decided, ""))
                    state.meta_set(f"baseline:{src.name}", self.stamp)
                if src.daily:
                    state.meta_set(f"daily:{src.name}", today)
                if getattr(src, "deep", False):
                    reached = getattr(src, "deep_reached", None) or {}
                    state.meta_set(f"dubinsko_str:{src.name}", json.dumps(reached))
                    if not reached:                 # cijeli popis pročitan: do sutra ne treba
                        state.meta_set(f"dubinsko:{src.name}", today)
                    self._deep_health(state, src, done=not reached)
                state.conn.commit()
                # Red obavijesti se sprema odmah: ako pokretanje stane prije slanja (istek
                # vremena, prekid), sljedeće ih pošalje i kad ih portal više ne prikazuje.
                self._remember_unsent(state, self._prev_unsent + to_notify)

            if baseline:
                self._send_baseline(state, baseline)
            to_notify += self._unsent(state, seen, {x.key for x, _, _ in to_notify})
            self._remember_unsent(state, to_notify)   # bez zastarjelih (poslani u međuvremenu, utišani)
            if len(to_notify) <= self.cfg.get("obavijesti", {}).get("max_poruka_po_pokretanju", 30):
                deadline = time.monotonic() + LAND_CHECK_SECONDS
                for x, d, _ in to_notify:
                    self._check_land(x, d, deadline)
            self._send_notifications(state, to_notify)
            if self.wants_telegram and not self.telegram:
                # Trebao bi slati: kao Telegram koji ne radi (GitHub to vidi i na Redmiju), i kad
                # nema oglasa – inače bi tišina izgledala kao "nema novih oglasa".
                self._telegram_health(state, "Telegram nije postavljen (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)")
            try:
                self._tenders(state, prices)
            except Exception as exc:  # noqa: BLE001 – natječaji ne smiju zaustaviti oglase
                self.log(f"Natječaji: GREŠKA {type(exc).__name__}: {exc}")
                traceback.print_exc()
            try:
                self._banks(state)
            except Exception as exc:  # noqa: BLE001
                self.log(f"Banke: GREŠKA {type(exc).__name__}: {exc}")
                traceback.print_exc()
            try:
                self._ppv_reminder(state)
            except Exception as exc:  # noqa: BLE001
                self.log(f"PPV podsjetnik: GREŠKA {type(exc).__name__}: {exc}")
            self._retry_weekly(state)
            self._retry_alerts(state)
            state.meta_set("last_run", self.stamp)
            if self.redmi_db:
                self._check_redmi(state)
            if self.device == "redmi":
                self._check_github(state)
            if self.device == "github":
                self._export(state)
        except BaseException:
            # Prekid (Ctrl+C, otkazan posao) usred obrade: nezapisano se odbacuje, kao kad proces
            # ubije sustav – inače bi nova cijena ostala zapisana, a obavijest o sniženju ne bi čekala.
            state.conn.rollback()
            raise
        finally:
            state.close()

    def _enrich(self, x: Listing, d: Decision, prices) -> None:
        """Usporedbe cijena u poruci. Greška u njima ne smije zadržati obavijest: oglas stiže bez njih."""
        try:
            x.extra["ppv"] = self.ppv.note(x, d.jls)
            area, place, short = prices.describe(x, d.jls) if prices else (None, None, None)
            x.extra["prosjek"], x.extra["usporedba"] = area, place
            x.extra["cijena_kratko"] = [t for t in (short, self.ppv.short(x, d.jls)) if t]
        except Exception as exc:  # noqa: BLE001
            self.log(f"Usporedba cijena za {x.key} nije izračunata: {type(exc).__name__}: {exc}")
            traceback.print_exc()

    def _main_trigger(self, state: State, reserve: bool) -> None:
        """Na GitHubu: rezerva (GitHubov raspored) radi samo kad cron-job.org kasni. Kasni li u
        radnom vremenu dulje od MAIN_TRIGGER_ALERT, upozorenje – portali se tada čitaju samo
        nekoliko puta dnevno, a sve izgleda ispravno. Oporavak tek kad cron-job.org ponovno pokrene."""
        if self.device != "github":
            return
        row = next((h for h in state.health_all() if h["source"] == "cron-job"), None)
        if not reserve:
            if row and row.get("failures"):
                state.health_ok("cron-job", self.stamp)
                if row.get("alerted"):
                    self._alert("Scraper: cron-job.org ponovno pokreće GitHub",
                                f"Redovna pokretanja (svakih 20 minuta) ponovno rade od {self.stamp[:16].replace('T', ' ')}.")
            return
        main = state.meta_get("glavni_okidac")
        age = self._age(main) if main else None
        if age is None:
            return                       # glavni okidač još nije radio (prvo postavljanje)
        start = self.now.replace(hour=self.cfg["vrijeme"]["od_sata"], minute=0, second=0, microsecond=0)
        late = min(age, max(self.now - start, timedelta(0)))      # noć se ne broji
        failures, alerted = state.health_fail("cron-job", f"zadnje redovno pokretanje {main[:16]}")
        if late >= MAIN_TRIGGER_ALERT and not alerted and self._alert(
                "Scraper: cron-job.org ne pokreće GitHub",
                f"cron-job.org nije pokrenuo scraper na GitHubu od {main[:16].replace('T', ' ')}. GitHub ga pokreće "
                "samo povremeno po svom rasporedu (rezerva), pa se portali osim Njuškala ne čitaju svakih 20 "
                "minuta. Provjeri na cron-job.org povijest pokretanja i je li posao uključen; ako piše greška "
                "401 ili 403, istekao je ili je promijenjen token za GitHub (README, cron-job.org). "
                "Javi Claudeu ovu poruku.") is not False:
            state.mark_alerted("cron-job")

    def _heartbeat(self, state: State) -> None:
        """Početak pokretanja, zapisan odmah: nadzor drugog uređaja razlikuje "ne javlja se" od
        "pokreće se, ali ne završava" (prekid, greška pri kraju). Redmi bilježi i kod i sat."""
        state.meta_set("pocetak", self.stamp)
        if self.device == "redmi":
            state.meta_set("kod", self._code_version())
            self._clock(state)
        state.conn.commit()
        if self.device == "github":
            path = Path(self.db_path).with_name("github.json")
            try:
                info = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                info = {}
            info.update(pocetak=self.stamp, glavni_okidac=state.meta_get("glavni_okidac"))
            tmp = path.with_name("github.json.tmp")
            tmp.write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)

    @staticmethod
    def _code_version() -> str:
        """Verzija koda ("<sha> <vrijeme commita>"), za usporedbu Redmija s GitHubom."""
        try:
            out = subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%H %cI"],
                                 capture_output=True, text=True, timeout=20)
            return out.stdout.strip() if out.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            return ""

    def _clock(self, state: State) -> None:
        """Na Redmiju: koliko sat mobitela odstupa od GitHubova (izmjereno pri preuzimanju stanja,
        sat.txt). Zapisuje se u redmi.db (GitHub njime ispravlja vrijeme Redmija); odstupa li više od
        CLOCK_TOLERANCE, poruka – inače nadzor laže (Redmi "živ" u budućnosti ili "mrtav" a radi)."""
        try:
            skew = float(Path(self.seen_file).with_name("sat.txt").read_text().strip())
        except (TypeError, OSError, ValueError):
            return
        self.skew = timedelta(seconds=skew)
        state.meta_set("sat:razlika", str(int(skew)))
        self._clock_health(state, self.skew)

    def _clock_health(self, state: State, skew: timedelta) -> None:
        row = next((h for h in state.health_all() if h["source"] == "sat"), None)
        if abs(skew) <= CLOCK_TOLERANCE:
            if row and row.get("failures"):
                state.health_ok("sat", self.stamp)
                if row.get("alerted"):
                    self._alert("Scraper: sat na Redmiju je ponovno točan", "Nadzor Redmija i GitHuba ponovno radi.")
            return
        minutes = int(abs(skew).total_seconds() // 60)
        what = f"{'žuri' if skew > timedelta(0) else 'kasni'} {minutes} min"
        _, alerted = state.health_fail("sat", f"sat na Redmiju {what}")
        if not alerted and self._alert(
                "Scraper: sat na Redmiju nije točan",
                f"Sat na Redmiju {what}. Dok se ne ispravi, nadzor Redmija i GitHuba može lagati (pogrešno "
                "„ne radi” ili propuštena prava greška). Na Redmiju: Postavke → Dodatne postavke → Datum i "
                "vrijeme → uključi automatsko vrijeme. Ako je već uključeno, javi Claudeu ovu poruku.") is not False:
            state.mark_alerted("sat")

    def _mail_health(self, state: State) -> None:
        """Na GitHubu: mail nije postavljen (obrisan ili preimenovan SMTP_USER/SMTP_PASSWORD).
        Bez njega ne stiže tjedni izvještaj ni upozorenje kad Telegram ne radi – javi se na Telegram."""
        if not self.wants_email:
            return
        row = next((h for h in state.health_all() if h["source"] == "mail"), None)
        if self.email:
            if row and row.get("failures"):
                state.health_ok("mail", self.stamp)
                if row.get("alerted"):
                    self._alert("Scraper: mail je ponovno postavljen", "Tjedni izvještaj i upozorenja ponovno idu mailom.")
            return
        _, alerted = state.health_fail("mail", "nema SMTP_USER ili SMTP_PASSWORD")
        if not alerted and self._alert(
                "Scraper: mail nije postavljen",
                "Na GitHubu nedostaju SMTP_USER ili SMTP_PASSWORD (Settings → Secrets and variables → Actions). "
                "Dok se ne upišu, ne stiže tjedni izvještaj, a ni upozorenje kad Telegram ne radi. "
                "Javi Claudeu ovu poruku.") is not False:
            state.mark_alerted("mail")

    def _repair_silent_twins(self, state: State) -> None:
        """Jednokratno: oglasi označeni "isti kao" tiho zabilježen oglas (početak praćenja,
        stari oglas) smatrali su se poslanima, a korisnik nijedan nije vidio. Oznaka se briše,
        pa stižu kad se ponovno pojave."""
        marks = {k: m or "" for k, m in state.conn.execute("SELECT key, notified_at FROM listings")}
        if self._redmi_usable():
            other = State(self.redmi_db)
            marks.update({k: m or "" for k, m in other.conn.execute("SELECT key, notified_at FROM listings")
                          if k not in marks})
            other.close()

        def ends_silent(key: str) -> bool:
            for _ in range(10):
                mark = marks.get(key, "")
                if not mark.startswith("dup:"):
                    return mark.startswith("tiho:")
                key = mark[4:]
            return False

        keys = [k for k, m in state.conn.execute("SELECT key, notified_at FROM listings WHERE notified_at LIKE 'dup:%' "
                                                 "AND status != ?", (REJECT,)) if ends_silent(m[4:])]
        for k in keys:
            state.conn.execute("UPDATE listings SET notified_at = NULL, notified_price = NULL WHERE key = ?", (k,))
        state.meta_set("popravak:tiho_duplikati", self.stamp)
        state.conn.commit()
        if keys:
            self.log(f"Isti kao tiho zabilježen oglas (nije poslan): {len(keys)} oglasa opet može stići")

    def _prune(self, state: State) -> None:
        """Jednom dnevno: odbijeni oglasi koji se dugo ne pojavljuju (State.prune); s našeg
        područja nakon godine dana (koliko gleda usporedba cijena), ostali nakon PRUNE_DAYS."""
        today = self.now.date().isoformat()
        if state.meta_get("ciscenje:dan") == today:
            return
        ours = {j.name for j in self.locator.jls.values() if j.included}
        n = state.prune(ours, (self.now - timedelta(days=MAX_AGE_DAYS)).isoformat(timespec="seconds"),
                        (self.now - timedelta(days=PRUNE_DAYS)).isoformat(timespec="seconds"))
        state.meta_set("ciscenje:dan", today)
        state.conn.commit()
        if n:
            state.conn.execute("VACUUM")             # datoteka se stvarno smanji
            self.log(f"Čišćenje baze: obrisano {n} starih odbijenih oglasa")

    def _read_feedback(self, state: State) -> None:
        """Pritisci gumba "Ne zanima me" od zadnjeg pokretanja (čita ih samo GitHub, i za
        poruke s Redmija – isti bot). Oglas se zapamti, gumb se zamijeni oznakom."""
        if self.device != "github" or not self.telegram or not hasattr(self.telegram, "get_updates"):
            return
        try:
            # Bez pomaka (offset): Telegram vraća sve nepotvrđene pritiske. Zapamćeni pomak bi
            # odbacio pritisak s manjim brojem – a broj je nasumičan nakon tjedan dana bez
            # ijednog pritiska, i drugačiji kad se bot zamijeni novim. Potvrda je na kraju.
            updates = self.telegram.get_updates(None)
        except Exception as exc:  # noqa: BLE001 – gumb nije nužan za rad
            self.log(f"Telegram (gumbi): {type(exc).__name__}: {exc}")
            return
        clicks = [u for u in updates if u.get("callback_query")]
        if clicks:
            self.log(f"Telegram (gumbi): {len(clicks)} novih pritisaka")
        if hasattr(self.telegram, "webhook_info"):
            try:                        # dijagnostika: stiže li išta ovom botu (bez imena u javnom zapisu)
                info, name = self.telegram.webhook_info(), self.telegram.me().get("username") or "?"
                other = sum(1 for u in clicks if str(((u["callback_query"].get("message") or {}).get("chat") or {})
                                                     .get("id")) != str(self.telegram.chat_id))
                kinds = [f"{u.get('update_id')}:{next((k for k in u if k != 'update_id'), '?')}" for u in updates]
                self.log(f"Telegram (gumbi): bot @{name[:2]}…{name[-5:]}, pritisaka {len(clicks)} (iz drugog "
                         f"razgovora {other}), ažuriranja {', '.join(kinds) or '-'}, na čekanju "
                         f"{info.get('pending_update_count')}, webhook {'da' if info.get('url') else 'ne'}, "
                         f"dopušteno {info.get('allowed_updates') or 'zadano'}, "
                         f"greška {info.get('last_error_message') or '-'}")
            except Exception as exc:  # noqa: BLE001
                self.log(f"Telegram (gumbi, provjera): {type(exc).__name__}: {exc}")
        self._handle_updates(state, updates)

    def _press(self, u: dict) -> tuple[str, str] | None:
        """Pritisak gumba: odmah oznaka na gumbu i odgovor Telegramu; vraća (radnja, ključ)
        za zapis u bazu, ili None (probni gumb, drugi razgovor, nešto drugo). Ne dira bazu,
        pa ga smije zvati i nit koja čeka pritiske."""
        reaction = u.get("message_reaction")
        if reaction:                         # 👎 na poruci oglasa = "Ne zanima me"; maknuta = poništenje
            if str((reaction.get("chat") or {}).get("id")) != str(self.telegram.chat_id):
                return None
            before = {r.get("emoji") for r in reaction.get("old_reaction") or []}
            after = {r.get("emoji") for r in reaction.get("new_reaction") or []}
            self.log(f"Reakcija na poruku {reaction.get('message_id')}: {''.join(sorted(before)) or '-'} → "
                     f"{''.join(sorted(after)) or '-'}")
            if DISLIKE in after and DISLIKE not in before:
                return "mute_msg", str(reaction.get("message_id"))
            if DISLIKE in before and DISLIKE not in after:
                return "unmute_msg", str(reaction.get("message_id"))
            return None
        q = u.get("callback_query") or {}
        message = q.get("message") or {}
        data = q.get("data") or ""
        if str((message.get("chat") or {}).get("id")) != str(self.telegram.chat_id):
            return None
        if data.startswith(MUTE_PREFIX):
            key = data[len(MUTE_PREFIX):]
            press, markup, answer = ("mute", key), muted_markup(message, key), "Zabilježeno"
        elif data.startswith(UNMUTE_PREFIX):
            key = data[len(UNMUTE_PREFIX):]
            press, markup, answer = ("unmute", key), unmuted_markup(message, key), "Poništeno – poruke opet stižu"
        else:
            return None
        calls = [lambda: self.telegram.answer_callback(q["id"], answer)]
        if markup:
            calls.insert(0, lambda: self.telegram.edit_markup(message["chat"]["id"], message["message_id"], markup))
        for call in calls:
            try:
                call()
            except Exception as exc:  # noqa: BLE001 – stari upit ili poruka: nije bitno
                self.log(f"Telegram (gumbi): {type(exc).__name__}: {exc}")
        return press

    def _record_presses(self, state: State, presses: list[tuple[str, str]]) -> None:
        presses = self._resolve_reactions(state, presses)
        for action, key in presses:
            if action == "mute":
                state.mute(key, self.stamp, "gumb")
                self.log(f"Ne zanima me: {key}")
            else:
                state.unmute(key)
                self.log(f"Ne zanima me poništeno: {key}")
        if presses:
            self.muted = state.muted(self._github_info().get("utisani"))
            state.conn.commit()

    def _resolve_reactions(self, state: State, presses: list[tuple[str, str]]) -> list[tuple[str, str]]:
        """Reakcija nosi samo broj poruke: oglas se traži među porukama koje je poslao GitHub
        ili Redmi. Poruka s Redmija poslana nakon učitavanja njegova stanja još nije poznata –
        takva reakcija čeka sljedeće pokretanje (najviše 2 dana). Oznaka na gumbu se mijenja
        kao kod pritiska."""
        try:
            waiting = json.loads(state.meta_get("reakcije:cekaju") or "[]")
        except ValueError:
            waiting = []
        oldest = (self.now - timedelta(days=2)).isoformat(timespec="seconds")
        todo = [(a, m, t) for a, m, t in waiting if t >= oldest]
        todo += [(a, m, self.stamp) for a, m in presses if a.endswith("_msg")]
        if not todo and not waiting:
            return presses
        other = State(self.redmi_db) if self._redmi_usable() else None
        out, still = [p for p in presses if not p[0].endswith("_msg")], []
        try:
            for action, message_id, at in todo:
                key = state.message_key(int(message_id)) or (other.message_key(int(message_id)) if other else None)
                if not key:
                    still.append((action, message_id, at))
                    continue
                kind = action.removesuffix("_msg")
                out.append((kind, key))
                row = state.get(key) or (other.get(key) if other else None) or {}
                links = {"reply_markup": {"inline_keyboard": [[{"text": "Otvori oglas", "url": safe_url(row["url"])}]]}} \
                    if row.get("url") else {}
                markup = muted_markup(links, key) if kind == "mute" else unmuted_markup(links, key)
                try:
                    self.telegram.edit_markup(self.telegram.chat_id, int(message_id), markup)
                except Exception as exc:  # noqa: BLE001 – oznaka nije bitna, zapis jest
                    self.log(f"Telegram (reakcija): {type(exc).__name__}: {exc}")
        finally:
            if other:
                other.close()
        if still:
            self.log(f"Reakcija 👎 na poruku koja još nije poznata (Redmi): {len(still)} čeka sljedeće pokretanje")
        state.meta_set("reakcije:cekaju", json.dumps(still))
        return out

    def _handle_updates(self, state: State, updates: list[dict]) -> None:
        """Pritisci "Ne zanima me" / poništenje: oznaka na gumbu, odgovor Telegramu, zapis u
        bazu; zatim potvrda (pomak) da se isti više ne vraćaju. Bez novih ažuriranja se
        ipak obrađuju 👎 koje čekaju poruku s Redmija."""
        if not updates:
            self._record_presses(state, [])
            state.conn.commit()
            return
        self._record_presses(state, [p for u in updates if (p := self._press(u))])
        offset = max(int(u["update_id"]) for u in updates) + 1
        state.meta_set("telegram:offset", str(offset))
        state.conn.commit()                  # zapisano, pa tek onda potvrđeno Telegramu
        try:
            self.telegram.get_updates(offset)
        except Exception as exc:  # noqa: BLE001 – nepotvrđeni se ponove (isti ishod)
            self.log(f"Telegram (gumbi, potvrda): {type(exc).__name__}: {exc}")

    def _export(self, state: State) -> None:
        """Za Redmi: sažetak viđenih oglasa, zadnje pokretanje (nadzor GitHuba) i oglasi
        označeni "Ne zanima me"."""
        dedupe.export(state, Path(self.db_path).with_name("seen.json.gz"))
        info = Path(self.db_path).with_name("github.json.tmp")
        info.write_text(json.dumps({"zadnje_pokretanje": self.stamp, "pocetak": self.stamp,
                                    "glavni_okidac": state.meta_get("glavni_okidac"), "utisani": sorted(state.muted())},
                                   ensure_ascii=False), encoding="utf-8")
        info.replace(info.with_suffix(""))

    def _load_pending(self, state: State, name: str) -> list[Listing]:
        """Oglasi koje izvor prošli put nije stigao otvoriti (izvor ih otvara ovaj put)."""
        try:
            return [Listing(**d) for d in json.loads(state.meta_get(f"odgodjeno:{name}") or "[]")]
        except (TypeError, ValueError) as exc:
            self.log(f"Odgođeni oglasi ({name}) nisu učitani: {exc}")
            return []

    def _github_info(self) -> dict:
        """Na Redmiju: podaci s GitHuba (github.json uz sažetak viđenih oglasa)."""
        if self.device == "github" or not self.seen_file:
            return {}
        try:
            data = json.loads(Path(self.seen_file).with_name("github.json").read_text(encoding="utf-8"))
            return {"zadnje_pokretanje": data.get("zadnje_pokretanje"), "pocetak": data.get("pocetak"),
                    "glavni_okidac": data.get("glavni_okidac"), "utisani": set(data.get("utisani") or [])}
        except (OSError, ValueError):
            return {}

    def _is_muted(self, state: State, seen: dedupe.Seen, x: Listing, d: Decision, old: dict | None = None) -> bool:
        """"Ne zanima me" za ovaj oglas ili isti oglas na drugom portalu."""
        if x.key in self.muted:
            self.log(f"Ne zanima (označeno): {x.title[:60]}")
            return True
        # Isti oglas po istim brojkama (±1 %), sad ili prije promjene cijene. Jeftinija kuća iste
        # površine u istom mjestu može biti druga nekretnina – ona stiže kao "već viđen … sad
        # jeftiniji", ne utiša se.
        rows = [dedupe.row(x, d)]
        if old and old.get("price") and old["price"] != x.price:
            rows.append({**dedupe.row(x, d), "price": old["price"]})
        twin = next((t["key"] for r in rows for t in seen.twins(r, cheaper_ok=False) if t["key"] in self.muted), None)
        if twin:
            self.muted.add(x.key)
            state.mute(x.key, self.stamp, f"isti kao {twin}")
            self.log(f"Ne zanima (isti kao {twin}): {x.title[:60]}")
            return True
        return False

    @staticmethod
    def _keep_text_reject(d: Decision, prev: dict, on_request: bool = False) -> Decision:
        """Oglas odbijen zbog podatka sa stranice oglasa (rečenica iz punog opisa, vrsta kuće
        ili zemljišta, luksuz iz opisa kod "cijene na upit") ostaje odbijen kad ovaj put imamo
        samo podatke s popisa – inače bi stiglo lažno "sad odgovara"."""
        labels = tuple(r.label for r in risks.RULES if r.reject)
        kept = [r for r in json.loads(prev.get("reasons") or "[]")
                if r.startswith(labels) or "(vrsta: " in r
                or (r.startswith("nije građevinsko (") and not r.endswith("(naslov)"))
                or (on_request and r.startswith("cijena na upit – luksuzna"))]
        return Decision(REJECT, kept, jls=d.jls, location_evidence=d.location_evidence) if kept else d

    def _load_seen(self, state: State) -> dedupe.Seen:
        """Već viđeni oglasi: ova baza, baza s Redmija (na GitHubu) i sažetak s GitHuba (na Redmiju)."""
        seen = dedupe.Seen(self.locator)
        seen.add_state(state)
        if self._redmi_usable():
            other = State(self.redmi_db)
            seen.add_state(other)
            other.close()
        if self.seen_file and not Path(self.seen_file).exists():
            self.log("Sažetak viđenih oglasa s GitHuba ne postoji – oglasi poslani s GitHuba nisu poznati")
        try:
            seen.add_file(self.seen_file)
        except Exception as exc:  # noqa: BLE001 – oštećena datoteka (npr. prekinut prijenos)
            self.log(f"Sažetak viđenih oglasa nije učitan: {type(exc).__name__}: {exc}")
        return seen

    def _check_land(self, x: Listing, d: Decision, deadline: float | None = None) -> None:
        """Zemljište i kuća: građevinsko područje na točnoj lokaciji (ISPU), za zemljište i
        PPV i uvjeti gradnje iz prostornog plana."""
        self._check_ispu(x, d, deadline)
        if x.kind == LAND:
            self._building_rules(x, d)

    def _building_rules(self, x: Listing, d: Decision) -> None:
        """📏 najmanja čestica, kig i kis iz UPU-a naselja (inače PPU-a); dio naselja (izgrađeni /
        neizgrađeni) s ISPU-a kad ga plan razlikuje. Čestica manja od najmanje → ⚠."""
        jls = d.jls or x.municipality
        if not jls:
            return
        try:
            # Dio naselja s vlastitim UPU-om iz naslova ("Gornja Drenova", "Dobrinčevo"), koji
            # popis naselja ne zna; inače naselje kao drugdje (polje naselja, pa naslov). Polje
            # naselja koje nabraja više mjesta ("Muraj, Kornić, Lakmartin") ne bira plan.
            # Naslov bira plan samo kad sva mjesta koja spominje potpadaju pod isti plan ("Ika-Oprić"
            # da, skupna lokacija portala "Veprinac, Poljane" ne); naziv samog grada/općine ("Krk",
            # "Malinska") ne određuje naselje (kao u place_of).
            parts = [n for n in self.plans.places_in(jls, x.title) if self.locator.by_name(n) is None]
            others = {n for j, n in self.locator.scan_names(x.title) if j.name == jls and self.locator.by_name(n) is None
                      and n != "centar" and not any(f" {n} " in f" {p} " for p in parts)}
            covering = [self.plans.find(jls, n) for n in [*parts, *others]]
            same_plan = None not in covering and len({id(p) for p in covering}) == 1
            part = parts[0] if parts and same_plan else ""
            official = bool(part) and any(j.name == jls for j in self.locator.by_settlement(part))
            single = x.settlement if len(re.split(r"[,;/]", x.settlement or "")) == 1 else ""
            place = (self._lead_place(x, jls) or (part if not official else "")
                     or place_of(self.locator, jls, x.title, x.settlement)
                     or part or self.plans.place_in(jls, single) or x.settlement)
            found = self.plans.check(x, jls, place, x.extra.get("gp_dio", ""))
        except Exception as exc:  # noqa: BLE001 – uvjeti gradnje nisu nužni za obavijest
            self.log(f"Uvjeti gradnje ({x.key}): {type(exc).__name__}: {exc}")
            return
        if found:
            x.extra["uvjeti"], warning = found
            self._warn(d, warning)

    @staticmethod
    def _warn(d: Decision, warning: str) -> None:
        """⚠ uz oglas – jednom i kad se neposlana obavijest ponovno provjerava."""
        if warning and warning not in d.warnings:
            d.warnings.append(warning)
            if d.status == PASS:
                d.status = WARN

    def _lead_place(self, x: Listing, jls: str) -> str:
        """nekretnine.hr: "Građevinsko zemljište Vrh, Krk, Vrh, Pinezići, Krk" – mjesto odmah iza
        vrste je točna lokacija, ostalo je skupna lokacija portala. Naziv grada/općine ne vrijedi."""
        m = re.match(r"\s*\w+\s+zemlji\w*\s+([^,]+),", x.title or "") if x.source == "nekretnine_hr" else None
        if not m:
            return ""
        lead = fold(m.group(1))                 # cijeli naziv ("Sušačka draga" nije "Draga")
        names = {n for n in self.plans.places_in(jls, lead) if n == lead}
        names |= {n for j, n in self.locator.scan_names(m.group(1)) if j.name == jls and n == lead}
        return lead if names and lead != "centar" and self.locator.by_name(lead) is None else ""

    def _check_ispu(self, x: Listing, d: Decision, deadline: float | None = None) -> None:
        """Građevinsko područje na točnoj lokaciji (ISPU), za zemljište i PPV. Izvan
        građevinskog područja naselja → ⚠ (oglas i dalje stiže). Kuća bez točne lokacije:
        redak "nije provjereno" se prvi izostavlja kad je poruka preduga."""
        if x.kind not in (LAND, HOUSE):
            return
        if x.extra.get("gp") and "nije provjereno" not in x.extra["gp"]:
            return                       # provjereno prošli put (neposlana obavijest): lokacija je ista
        house = x.kind == HOUSE
        if deadline is not None and time.monotonic() > deadline:
            x.extra["gp"] = "🗺 Građevinsko područje: nije provjereno (vremensko ograničenje pokretanja)"
            x.extra["gp_neprovjereno"] = house
            return
        if self._ispu is None:
            self._ispu = Ispu()
        try:
            result = check_land(self._ispu, f"{x.title}. {x.description}", x.extra.get("lat"), x.extra.get("lon"),
                                bool(x.extra.get("priblizna_lokacija", True)), self._place_names, house=house,
                                radius=APPROX_RADIUS_M.get(x.source, APPROX_RADIUS_M["default"]))
        except Exception as exc:  # noqa: BLE001 – ISPU nije nužan za obavijest
            self.log(f"ISPU ({x.key}): {type(exc).__name__}: {exc}")
            x.extra["gp"] = "🗺 Građevinsko područje: nije provjereno (ISPU ne odgovara)"
            x.extra["gp_neprovjereno"] = house
            return
        x.extra["gp"] = result.line
        x.extra["gp_neprovjereno"] = house and result.info is None
        for warning in (result.warning, result.heritage):
            self._warn(d, warning)
        info = result.info
        if info and info.gp == "naselja" and info.use:
            use = info.use.upper()
            x.extra["gp_dio"] = "neizgrađeni dio" if "NEIZGRAĐENI" in use else "izgrađeni dio" if "IZGRAĐENI" in use else ""
        if info and info.land_values and x.price and x.area and x.price > 1000 and not house:
            low, high, ppm = min(info.land_values), max(info.land_values), x.price / x.area
            x.extra["ppv"] = land_note(ppm, low, high, f"na lokaciji, blok {info.block.title()}")
            x.extra["cijena_kratko"] = [t for t in x.extra.get("cijena_kratko", []) if not t.startswith("PPV")] \
                + [land_short(ppm, low, high)]

    def _tenders(self, state: State, prices: AskingPrices | None = None) -> None:
        """Natječaji za prodaju nekretnina (gradovi, općine, PGŽ, CERP…), jednom dnevno.
        Prvi put stižu samo objave iz zadnjih N dana kojima rok nije istekao; ostale se
        bilježe bez poruke."""
        cfg = self.cfg.get("natjecaji") or {}
        today = self.now.date().isoformat()
        if not cfg.get("ukljuceno", True) or self.device != "github" or not self.telegram:
            return
        if not state.meta_get("natjecaji:pravilo2"):
            # Jednokratno: prvi dan je prešutio i objave starije od 45 dana kojima rok još traje.
            state.conn.execute("DELETE FROM tenders WHERE notified_at LIKE 'tiho:%'")
            state.conn.execute("DELETE FROM meta WHERE key IN ('baseline:natjecaji', 'daily:natjecaji')")
            state.meta_set("natjecaji:pravilo2", self.stamp)
        if state.meta_get("daily:natjecaji") == today:
            return
        cutoff = (self.now - timedelta(days=cfg.get("dana_unazad_prvi_put", 45))).date().isoformat()
        oldest = (self.now - timedelta(days=cfg.get("najstarije_s_rokom", 180))).date().isoformat()
        reader = tenders.Reader(self.http, self.locator)
        new: list[tenders.Tender] = []
        first_sites: set[str] = set()   # stranice pročitane prvi put (početno stanje po stranici)
        for site in tenders.load_sites():
            name = f"natjecaji: {site['naziv']}"
            try:
                items = reader.fetch(site)
            except Exception as exc:  # noqa: BLE001
                failures, alerted = self._daily_fail(state, name, f"{type(exc).__name__}: {exc}")
                self.log(f"{name}: GREŠKA ({failures}. dan zaredom): {exc}")
                if failures >= 3 and not alerted and self._alert(
                        f"Scraper: natječaji – {site['naziv']} ne rade",
                        f"Stranica {site['url']} tri dana zaredom vraća grešku:\n{exc}\n\nJavi Claudeu ovu poruku.") is not False:
                    state.mark_alerted(name)
                continue
            state.health_ok(name, self.stamp)
            if state.meta_get(f"baseline:{name}") is None:
                first_sites.add(site["naziv"])
                state.meta_set(f"baseline:{name}", self.stamp)
            fresh = [t for t in items if not state.tender_known(t.key) and t.key not in {n.key for n in new}]
            self.log(f"{name}: {len(items)} objava o prodaji, novih {len(fresh)}")
            new.extend(fresh)
        limit = cfg.get("max_poruka", 15)
        deadline = time.monotonic() + TENDER_CHECK_SECONDS
        sent = 0
        for t in new:
            first = t.site in first_sites
            reader.load_text(t)
            published = t.published or t.extra.get("datum_iz_teksta", "")
            info = tenders.details(t.text, published) if t.text else {}
            # Približan rok ("15 dana od objave") može biti krivo izračunat: zbog njega se
            # natječaj ne preskače kao istekao, a prvi put vrijedi pravilo datuma objave.
            approximate = info.get("rok_priblizno")
            expired = info.get("rok") and not approximate and info["rok"] < today
            # Prvi put: rok poznat i nije istekao (objava do pola godine stara), ili bez roka
            # objava iz zadnjih 45 dana.
            open_deadline = info.get("rok") and not approximate and not expired and (not published or published >= oldest)
            if first and not open_deadline and (expired or not published or published < cutoff):
                state.tender_add(t, self.stamp, f"tiho:{self.stamp}")
                why = "rok istekao" if expired else "bez datuma i roka" if not published else f"objavljeno {published}"
                self.log(f"Natječaj bez poruke (prvo čitanje stranice, {why}): {t.title[:70]}")
                continue
            found = tenders.lots(t.text)
            outside = False
            if t.extra.get("regionalno"):     # PGŽ, CERP, Državne nekretnine: samo čestice na našem području
                ours = [x for x in found if reader.area_of(f"{x.context} {x.ko}")]
                # Tekst spominje naše područje i kad je to samo sjedište (npr. "Trgovački sud u
                # Rijeci"): bez ijedne naše čestice, ili bez čestica i bez našeg mjesta u naslovu, preskače se.
                outside = not ours and (bool(found) or not reader.area_of(t.title))
                found = ours
            jls = t.jls if t.jls and self.locator.by_name(t.jls) else ""
            where = tenders.place_text(t, found)
            # Odluke iz popisa naselja: odbija se samo naselje napisano u tekstu; prema k.o.
            # (može obuhvaćati više naselja) samo upozorenje.
            verdict = self.locator.settlement_verdict(jls, "", tenders.place_text(t, found, False)) if jls else None
            by_ko = self.locator.settlement_verdict(jls, "", where) if jls else None
            if by_ko and by_ko != verdict and not (verdict and verdict[0] == REJECT):
                note = " (prema k.o. – katastarska općina može obuhvaćati više naselja)" if by_ko[0] == REJECT else ""
                verdict = (WARN, f"{by_ko[1]}{note}")
            misses = tenders.fails_criteria(found, self.criteria)
            skip = ("istekao" if expired
                    else "regionalni natječaj – nijedna čestica na našem području" if outside
                    else "samo stanovi/poslovni prostori" if len(t.text) >= tenders.MIN_TEXT and tenders.flats_only(t.text)
                    else f"popis naselja – {verdict[1]}" if verdict and verdict[0] == REJECT
                    else f"ne odgovara kriterijima – {misses}" if misses
                    else "ograničenje" if sent >= limit else "")
            if skip == "ograničenje":       # ne bilježi se: stiže sutra
                self.log(f"Natječaj odgođen za sutra (najviše {limit} poruka dnevno): {t.title[:70]}")
                continue
            if skip:
                state.tender_add(t, self.stamp, f"tiho:{self.stamp}")
                self.log(f"Natječaj bez poruke ({skip}): {t.title[:70]}")
                continue
            try:
                text = self._tender_message(t, info, found, jls, where, verdict, prices, deadline)
            except Exception as exc:  # noqa: BLE001 – poruka i bez usporedbi
                self.log(f"Natječaj – detalji: {type(exc).__name__}: {exc}")
                traceback.print_exc()
                text = tenders.format_tender(t, info)
            try:
                self.telegram.send_text(text, url=t.url)
                state.tender_add(t, self.stamp, self.stamp)
                sent += 1
            except Exception as exc:  # noqa: BLE001
                self.log(f"Natječaj nije poslan ({t.url}): {exc}")
        state.meta_set("daily:natjecaji", today)
        state.conn.commit()
        self.log(f"Natječaji: novih {len(new)}, poslano {sent}")

    def _banks(self, state: State) -> None:
        """Stranice banaka s prodajom preuzetih nekretnina (data/banke.yaml), jednom dnevno:
        poruka samo za novi tekst koji spominje naše područje; prvo čitanje bez poruke."""
        today = self.now.date().isoformat()
        if self.device != "github" or not self.telegram or state.meta_get("daily:banke") == today:
            return
        for page in watch.load_pages():
            name, key = f"banke: {page['naziv']}", f"banke:{page['naziv']}"
            try:
                body = self.http.get(page["url"]).text
                if blocked(body):
                    raise RuntimeError(f"stranica zaštite ili održavanja: {blocked(body)}")
                if not watch.segments(body):
                    raise RuntimeError("stranica bez teksta")
            except Exception as exc:  # noqa: BLE001
                failures, alerted = self._daily_fail(state, name, f"{type(exc).__name__}: {exc}")
                self.log(f"{name}: GREŠKA ({failures}. dan zaredom): {exc}")
                if failures >= 3 and not alerted and self._alert(
                        f"Scraper: banke – {page['naziv']} ne radi",
                        f"Stranica {page['url']} tri dana zaredom vraća grešku:\n{exc}\n\nJavi Claudeu ovu poruku.") is not False:
                    state.mark_alerted(name)
                continue
            state.health_ok(name, self.stamp)
            stored = state.meta_get(key)
            known = set(json.loads(stored)) if stored else set()
            found, hashes = watch.changes(self.locator, body, known)
            if page.get("svaka_promjena"):        # najava (npr. novi oglasnik Butiga.hr): mail kod bilo koje promjene
                fresh = [s for s in watch.segments(body) if watch.digest(s) not in known]
                if stored is not None and fresh:
                    if self._alert(f"Scraper: promjena na stranici {page['naziv']}",
                                   f"{page['url']}\n\nNovo na stranici:\n" + "\n".join(fresh[:10])
                                   + "\n\nJavi Claudeu ako je pokrenut novi oglasnik.") is False:
                        continue                  # promjena se ne pamti: mail se ponavlja sutra
                    self.log(f"{name}: promjena ({len(fresh)} novih odlomaka)")
                found = []
            if stored is not None and found:
                try:
                    self.telegram.send_text(watch.format_change(page["naziv"], found), url=page["url"])
                except Exception as exc:  # noqa: BLE001 – novo se ne pamti: poruka se ponavlja
                    self.log(f"{name}: poruka nije poslana: {exc}")
                    continue
                self.log(f"{name}: novo s našim područjem ({len(found)})")
            state.meta_set(key, watch.dumps(hashes | known if len(known) < 5000 else hashes))
        state.meta_set("daily:banke", today)
        state.conn.commit()

    def _daily_fail(self, state: State, name: str, error: str) -> tuple[int, bool]:
        """Greška stranice koja se čita jednom dnevno broji se najviše jednom dnevno: ponovno
        čitanje istog dana (prekinuto pokretanje) ne skraćuje "tri dana zaredom"."""
        today = self.now.date().isoformat()
        row = next((h for h in state.health_all() if h["source"] == name), None)
        if row and row.get("failures") and state.meta_get(f"greska_dan:{name}") == today:
            state.conn.execute("UPDATE health SET last_error = ? WHERE source = ?", (error[:1000], name))
            return row["failures"], bool(row["alerted"])
        state.meta_set(f"greska_dan:{name}", today)
        return state.health_fail(name, error)

    def _ppv_reminder(self, state: State) -> None:
        """Nova godina: podsjetnik da se PPV osvježi (Telegram i mail). Zatim jednom dnevno
        provjera ISPU-a; kad objavi PPV za 1.1. nove godine, još jedan podsjetnik."""
        if self.device != "github" or not self.telegram or self.now.year <= PPV_YEAR:
            return
        today = self.now.date().isoformat()
        if state.meta_get("daily:ppv") == today:
            return
        how = "Na GitHubu: Actions → „PPV – godišnje osvježavanje” → Run workflow."
        if state.meta_get(f"ppv:nova_godina:{self.now.year}") is None:
            text = (f"Sretna Nova godina! PPV u porukama je još za 1.1.{PPV_YEAR}. Kad ISPU objavi PPV za "
                    f"1.1.{self.now.year}., javit ću da pokreneš osvježavanje. {how}\n\n"
                    f"Podsjetnik: razmisli o brisanju starih oglasa. Medijani traženih cijena gledaju oglase iz "
                    f"zadnjih {MAX_AGE_DAYS} dana, a odbijeni oglasi s našeg područja brišu se kad ispadnu iz "
                    f"tog razdoblja. Kraće razdoblje (npr. 6 mjeseci) bolje prati promjenu cijena, ali daje manje "
                    f"oglasa po naselju. Ako želiš promjenu, javi Claudeu.")
            self.telegram.send_text(f"🏛 <b>PPV</b>\n{html.escape(text)}")   # greška: ponovno sljedeći put
            self._email(f"Scraper: osvježi PPV ({self.now.year})", text)
            state.meta_set(f"ppv:nova_godina:{self.now.year}", self.stamp)
        if self._ispu is None:
            self._ispu = Ispu()
        year = self._ispu.ppv_year()
        if year and year > PPV_YEAR and state.meta_get(f"ppv:objavljen:{year}") is None:
            text = f"ISPU je objavio PPV za 1.1.{year}. Pokreni osvježavanje: {how}"
            self.telegram.send_text(f"🏛 <b>Novi PPV ({year})</b>\n{html.escape(text)}")
            self._email(f"Scraper: objavljen PPV {year}", text)
            state.meta_set(f"ppv:objavljen:{year}", self.stamp)
            self.log(f"PPV: objavljen {year}, poslan podsjetnik")
        state.meta_set("daily:ppv", today)

    def _tender_message(self, t: tenders.Tender, info: dict, found: list[tenders.Lot], jls: str, where: str,
                        verdict: tuple[str, str] | None, prices: AskingPrices | None, deadline: float) -> str:
        """Poruka za natječaj s istim podacima kao za oglase: sažeti redak (more, Rijeka,
        cijena), naselje, za svaku česticu građevinsko područje (ISPU), početna
        cijena po m² prema PPV-u na lokaciji i medijanu traženih, upozorenja."""
        warnings = [verdict[1]] if verdict else []
        mjere, place = {}, ""
        row = self.locator.settlement_row(jls, "", where) if jls else None
        if row:
            r, exact = row
            mjere = {"naselje": r["naziv"], "tocno": exact, "more_km": r["more_km"], "rijeka_min": r["rijeka_min"]}
            if exact and fold(r["naziv"]) != fold(jls):
                place = f"{jls} – {r['naziv']}"
        if not place and jls and jls not in t.site:
            place = jls
        settlement = mjere["naselje"] if mjere.get("tocno") else ""
        short: dict[int, list[str]] = {}
        for i, lot in enumerate(found):
            point = None
            # Zemljišnoknjižni broj (z.k.č.) na Krku često nije isti kao katastarski: katastar se ne pita.
            if i < 3 and time.monotonic() < deadline and not lot.land_registry:
                try:
                    if self._ispu is None:
                        self._ispu = Ispu()
                    hit = self._ispu.parcel(lot.ko, lot.kcs[0], self._place_names)
                    if hit:
                        lot.cadastre_area = hit.get("povrsina") if len(lot.kcs) == 1 else None
                        point = self._ispu.identify(hit["x"], hit["y"])
                        lot.gp = gp_text(point)
                    elif lot.price or lot.ppm or lot.area:      # inače broj iz teksta možda nije čestica
                        miss = getattr(self._ispu, "last_miss", "kc")
                        lot.gp = ("katastar nije odgovorio – nije provjereno" if miss == "off"
                                  else f"k.o. {lot.ko} nije pronađena u katastru" if miss == "ko"
                                  else "nije pronađena u katastru")
                except Exception as exc:  # noqa: BLE001 – ISPU nije nužan za obavijest
                    self.log(f"ISPU (natječaj): {type(exc).__name__}: {exc}")
                    deadline = 0
            if point and point.gp != "naselja" and not lot.house:
                warnings.append(f"{lot.label}: prema ISPU-u {gp_text(point)} – provjeri")
            if point and point.heritage:
                warnings.append(f"{lot.label}: {heritage_warning(point.heritage, land=not lot.house)}")
            unit = lot.unit_price
            parts = []
            if point and point.land_values:
                low, high = min(point.land_values), max(point.land_values)
                if unit and not lot.house:
                    lot.notes.append(land_note(unit, low, high, f"na lokaciji, blok {point.block.title()}", "početna cijena"))
                    parts.append(land_short(unit, low, high))
                elif not lot.house:                   # za kuće PPV ne postoji
                    span = f"{round(low)}" if round(low) == round(high) else f"{round(low)}–{round(high)}"
                    lot.ppv_range = f"PPV {span} €/m²"
            if unit and not lot.house and jls:
                size = lot.size or 1000.0     # usporedbe gledaju samo €/m² (cijena može biti zadana po m²)
                x = Listing("natjecaj", t.key, t.url, f"{t.title} {lot.ko}", LAND, price=unit * size, area=size,
                            settlement=settlement)
                if not lot.notes:
                    note = self.ppv.note(x, jls, "početna cijena")
                    if note:
                        lot.notes.append(note)
                        parts.append(self.ppv.short(x, jls) or "")
                if prices:
                    # Usporedba s oglasima po kriterijima ovisi o površini; bez nje medijan svih oglasa.
                    area_line, place_line, brief = prices.describe(x, jls) if lot.size else \
                        (None, prices.compare(x, jls), prices.short(x, jls))
                    lot.notes += [n for n in (area_line, place_line) if n]
                    parts.insert(0, brief or "")
            if unit:
                short[i] = [p for p in parts if p]
        if info.get("dio"):
            warnings.append("prodaje se dio nekretnine (suvlasnički udio) – provjeri")
        price_parts = next(iter(short.values())) if len(short) == 1 else []   # više čestica: usporedbe su uz svaku
        summary = summary_text(mjere, price_parts, len(warnings))
        return tenders.format_tender(t, info, found, summary, place, warnings)

    def _load_prices(self, state: State) -> AskingPrices | None:
        """Medijani traženih cijena: na GitHubu iz baza (i spremi za Redmi), na Redmiju iz
        datoteke s GitHuba (Redmijeva baza ima samo Njuškalo)."""
        try:
            if self.device != "github" and self.prices_file and Path(self.prices_file).exists():
                return AskingPrices.from_file(self.prices_file, self.locator)
            rows = state.price_rows()
            if self._redmi_usable():
                other = State(self.redmi_db)
                rows += other.price_rows()
                other.close()
            prices = AskingPrices.from_rows(rows, self.locator, self.now, self.criteria)
            if self.device == "github":
                prices.save(Path(self.db_path).with_name("cijene.json"))
            return prices
        except Exception as exc:  # noqa: BLE001 – usporedba nije nužna za obavijest
            self.log(f"Medijani cijena nisu učitani: {type(exc).__name__}: {exc}")
            return None

    def _check_seen(self, state: State, seen: dedupe.Seen, x: Listing, d: Decision, old: dict | None,
                    headline: str) -> str | None:
        """Isti oglas već viđen (drugi portal, ponovna objava)? Stiže samo ako je sad jeftiniji."""
        new = dedupe.row(x, d)
        # Kopija zabilježena kao "isti kao ovaj oglas" (izravno ili preko druge kopije) ne znači
        # da je poruka stigla: ako slanje nije uspjelo, sljedeće pokretanje ga ponovno šalje.
        twins = [t for t in seen.twins(new) if seen.delivered(t, x.key)]
        if twins:
            def lowest(r):                   # cijena do 100 € je zamjena za "cijena na upit"
                values = [v for v in (r["price"], r.get("notified_price")) if v and v > 100]
                return min(values) if values else None
            cheapest = min(twins, key=lambda r: lowest(r) or float("inf"))
            low = lowest(cheapest)

            def same_price(r):               # ±1 % od cijene koju blizanac ima ili je imao u poruci
                return any(v and v > 100 and abs(x.price - v) <= v * dedupe.PRICE_TOLERANCE
                           for v in (r["price"], r.get("notified_price")))
            if x.price and low is not None and x.price >= low * (1 - dedupe.PRICE_TOLERANCE) \
                    and not any(same_price(t) for t in twins):
                # Nije jeftinija ni iste cijene: "do 30 % skuplji raniji oglas" vrijedi samo za
                # sniženja, pa je ovo druga kuća (blizanac je u međuvremenu poskupio).
                twins = []
        if twins:
            if not x.price or low is None or x.price >= low * (1 - dedupe.PRICE_TOLERANCE):
                if old is None or not old.get("notified_at"):
                    # Zabilježen kao viđen i kad je red već postojao (npr. nakon poništenja
                    # "Ne zanima me"): inače se provjerava svaki put, a kasnije sniženje stiže
                    # kao "sad odgovara kriterijima".
                    state.mark_notified(x.key, x.price, f"dup:{cheapest['key']}")
                self.log(f"Već viđen ({cheapest['key']}): {x.title[:60]}")
                return None
            if old is None:
                where = SOURCE_LABELS.get(cheapest["source"], cheapest["source"])
                headline = f"📉 Već viđen na {where} za {fmt_eur(low)} – sad jeftiniji"
            x.extra["blizanci"] = [t["key"] for t in twins]   # usporedba cijena: bez same sebe
        new["notified_at"], new["notified_price"] = self.stamp, x.price
        seen.add(new)  # drugi portal u istom pokretanju ne šalje isti oglas ponovno
        return headline

    def _notify_reason(self, x: Listing, d: Decision, old: dict | None) -> str | None:
        """Naslov obavijesti ili None ako se ne šalje ništa."""
        if not d.notify:
            return None
        if old is None:
            return ""
        # Ukupne cijene: "1 €" (cijena na upit) ili cijena po m² nisu sniženje.
        total = bool(x.extra.get("ukupna_cijena"))
        price = effective_price(x.price, x.area, total, x.kind)
        # Cijena iz zadnje poruke (ili tihog bilježenja).
        ref = (effective_price(old.get("notified_price"), old.get("area") or x.area, total, x.kind)
               if old.get("notified_at") else None)
        # Prošli put "cijena na upit" (1 € ili bez cijene): uspoređuje se s cijenom iz poruke.
        old_price = effective_price(old.get("price"), old.get("area") or x.area, total, x.kind) or ref
        if price and old_price and price < old_price - 1:
            # Poskupljenje pa malo pojeftinjenje, a i dalje skuplje nego u poruci, nije sniženje.
            if ref and price >= ref - 1:
                return None
            change = f"{fmt_eur(ref or old_price)} → {fmt_eur(price)}"
            if old.get("notified_at"):
                return f"📉 Snižena cijena: {change}"
            return f"📉 Snižena cijena ({change}) – sad odgovara kriterijima"
        if not old.get("notified_at"):
            # Prije odbijen, a sad odgovara (npr. ispravljena površina) ili slanje nije uspjelo.
            return "" if old.get("status") != REJECT else "🔄 Sad odgovara kriterijima (izmijenjen oglas ili pravila pretrage)"
        return None

    def _send_notifications(self, state: State, to_notify) -> None:
        if not to_notify:
            self.log("Nema novih oglasa za obavijest.")
            return
        limit = self.cfg.get("obavijesti", {}).get("max_poruka_po_pokretanju", 30)
        if not self.telegram:
            self.log(f"{len(to_notify)} obavijesti (Telegram nije postavljen):")
            for x, d, h in to_notify:
                self.log(f"  {h} {x.title} | {x.url}")
            return
        if len(to_notify) > limit:
            entries = [report.entry(x, d) for x, d, _ in to_notify]
            path = self._report("novi-oglasi", "Novi oglasi", entries, [])
            if self._send_report(path, f"<b>{len(to_notify)} novih oglasa</b> – previše za pojedinačne poruke, popis je u datoteci.",
                                 "Scraper: puno novih oglasa", mail=False) is False:
                self._remember_unsent(state, to_notify)     # pokušava se ponovno sljedeći put
                self._telegram_health(state, "zbirna datoteka nije poslana")
                return
            self._telegram_health(state, None)
            for x, _, _ in to_notify:
                state.mark_notified(x.key, x.price, f"zbirno:{self.stamp}")
            self._remember_unsent(state, [])
            return
        sent, failed, error = 0, [], ""
        for x, d, headline in to_notify:
            try:
                message_ids = self.telegram.send_listing(x, d, headline)
                state.mark_notified(x.key, x.price, self.stamp)
                for message_id in message_ids or []:     # za reakciju 👎 (nosi samo broj poruke)
                    state.remember_message(message_id, x.key, self.stamp)
                state.conn.commit()          # poslano je poslano, i ako pokretanje odmah stane
                sent += 1
            except Exception as exc:  # noqa: BLE001
                self.log(f"Obavijest nije poslana ({x.key}): {exc}")
                failed.append((x, d, headline))
                error = error or f"{type(exc).__name__}: {exc}"
        self._remember_unsent(state, failed)
        self._telegram_health(state, None if sent else error)
        self.log(f"Poslano obavijesti: {sent}/{len(to_notify)}")

    def _telegram_health(self, state: State, error: str | None) -> None:
        """Telegram ne prima ništa (blokiran bot, promijenjen token): nakon 3 pokretanja
        zaredom jedan mail; kad proradi, još jedan. Inače bi tišina izgledala kao "nema oglasa"."""
        row = next((h for h in state.health_all() if h["source"] == "telegram"), None)
        if error is None:
            if row and row.get("failures"):
                state.health_ok("telegram", self.stamp)
                if row.get("alerted"):
                    self.email_ok("Scraper: Telegram ponovno radi", "Obavijesti ponovno stižu na Telegram; neposlane su poslane.")
            return
        failures, alerted = state.health_fail("telegram", error[:300])
        if failures < 3 or alerted:
            return
        if error.startswith("Telegram nije postavljen"):
            subject = "Scraper: Telegram nije postavljen"
            text = (f"Telegram nije postavljen {failures} pokretanja zaredom: nedostaju TELEGRAM_BOT_TOKEN ili "
                    "TELEGRAM_CHAT_ID. Na GitHubu ih upiši u Settings → Secrets and variables → Actions (na Redmiju "
                    "u ~/.scraper.env). Obavijesti dotad ne stižu (čekaju najviše 7 dana). Javi Claudeu ovu poruku.")
        else:
            subject = "Scraper: Telegram ne prima poruke"
            text = (f"Telegram {failures} pokretanja zaredom odbija sve poruke:\n{error}\n\nProvjeri da bot nije "
                    "blokiran ili obrisan. Neposlane obavijesti čekaju (najviše 7 dana). Javi Claudeu ovu poruku.")
        if self.email_ok(subject, text):
            state.mark_alerted("telegram")

    def _remember_unsent(self, state: State, items) -> None:
        """Neposlane obavijesti čekaju sljedeće pokretanje i kad ih portal više ne prikazuje
        (novi oglasi su ih pomaknuli dalje od pročitanih stranica). "od" ostaje prvo vrijeme."""
        out, keys = [], set()
        for x, d, h in items:
            if x.key not in keys:
                keys.add(x.key)
                out.append({"oglas": x.to_dict(), "odluka": dataclasses.asdict(d), "naslov": h,
                            "od": self._unsent_since.get(x.key, self.stamp)})
        state.meta_set("neposlano", json.dumps(out, ensure_ascii=False))
        state.conn.commit()

    def _load_unsent(self, state: State) -> list[tuple[Listing, Decision, str]]:
        out = []
        try:
            items = json.loads(state.meta_get("neposlano") or "[]")
        except ValueError:
            return out
        for item in items:
            try:
                x, d = Listing(**item["oglas"]), Decision(**item["odluka"])
            except (TypeError, KeyError):
                continue
            self._unsent_since[x.key] = item.get("od", self.stamp)
            out.append((x, d, item.get("naslov", "")))
        return out

    def _unsent(self, state: State, seen: dedupe.Seen, queued: set[str]) -> list[tuple[Listing, Decision, str]]:
        """Obavijesti koje prošli put nisu poslane (najviše 7 dana stare), osim ako su u
        međuvremenu poslane (i kao isti oglas s drugog portala), oglas je odbijen ili
        označen "Ne zanima me"."""
        out = []
        oldest = (self.now - timedelta(days=UNSENT_DAYS)).isoformat(timespec="seconds")
        for x, d, headline in self._prev_unsent:
            row = state.get(x.key)
            if (x.key in queued or x.key in self.muted or self._unsent_since.get(x.key, "") < oldest or not row
                    or (row.get("notified_at") and not self._undelivered_drop(x, row)) or row.get("status") == REJECT):
                continue
            if any(seen.delivered(t, x.key) for t in seen.twins(dedupe.row(x, d), cheaper_ok=False)):
                continue
            out.append((x, d, headline))
        if out:
            self.log(f"Ponovno slanje neposlanih obavijesti: {len(out)}")
        return out

    @staticmethod
    def _undelivered_drop(x: Listing, row: dict) -> bool:
        """Sniženje koje nije stiglo: oglas je već javljen, a cijena u redu čekanja niža je od
        one iz zadnje poruke (cijena u bazi je već nova, pa ga _notify_reason više ne javlja)."""
        total = bool(x.extra.get("ukupna_cijena"))
        price = effective_price(x.price, x.area, total, x.kind)
        sent = effective_price(row.get("notified_price"), row.get("area") or x.area, total, x.kind)
        return bool(price and sent and price < sent - 1)

    def _send_baseline(self, state: State, baseline) -> None:
        entries, sources = [], []
        for src, decided, _ in baseline:
            entries.extend(report.entry(x, d) for x, d in decided)
            sources.append(self._source_summary(src, decided))
        matching = sum(1 for e in entries if e["st"] in (PASS, WARN))
        names = ", ".join(s["label"] for s in sources)
        path = self._report("pocetni-popis", "Početni popis oglasa", entries, sources,
                            note="Prvo pokretanje izvora: ovo su svi trenutno aktivni oglasi na području. "
                                 "Od sada stižu samo novi oglasi i snižene cijene.")
        if self._send_report(path, f"<b>Početni popis</b> ({names}): {matching} oglasa odgovara kriterijima "
                                   f"(✅ i ⚠), ukupno pregledano {len(entries)}.", "Scraper: početni popis oglasa") is False:
            # Popis nije stigao: sljedeće pokretanje ponovno čita cijelo područje i šalje ga.
            for src, _, _ in baseline:
                state.conn.execute("DELETE FROM meta WHERE key = ?", (f"baseline:{src.name}",))
            state.conn.commit()
            return
        for _, decided, _ in baseline:
            for x, d in decided:
                if d.notify:
                    state.mark_notified(x.key, x.price, f"zbirno:{self.stamp}")
        state.conn.commit()

    def _source_summary(self, src, decided) -> dict:
        out = {"label": src.label, "total": len(decided), "links": src.search_links()}
        for s in (PASS, WARN, REJECT):
            out[s] = sum(1 for _, d in decided if d.status == s)
        out["za_dlaku"] = sum(1 for _, d in decided if d.status == REJECT and d.near_miss)
        return out

    def _source_failed(self, state: State, src, exc: Exception) -> None:
        detail = f"{type(exc).__name__}: {exc}"
        failures, alerted = state.health_fail(src.name, detail)
        self.log(f"{src.label}: GREŠKA ({failures}. zaredom): {detail}")
        traceback.print_exc()
        limit = self.cfg.get("nadzor", {}).get("greske_prije_upozorenja", 3)
        if failures >= limit and not alerted and self._alert(
            f"Scraper: izvor {src.label} ne radi",
            f"Izvor {src.label} je {failures} puta zaredom vratio grešku.\n\nZadnja greška:\n{detail}\n\n"
            "Dok se ne popravi, s ovog izvora ne stižu obavijesti. Javi Claudeu ovu poruku.",
        ) is not False:                     # neuspjelo upozorenje se ponavlja sljedeće pokretanje
            state.mark_alerted(src.name)

    def _source_ok(self, state: State, src) -> None:
        row = next((h for h in state.health_all() if h["source"] == src.name), None)
        was_alerted = bool(row and row.get("alerted"))
        state.health_ok(src.name, self.stamp)
        if was_alerted:
            self._alert(f"Scraper: izvor {src.label} ponovno radi", f"Izvor {src.label} ponovno radi ({self.stamp}).")

    def _local(self, stamp: str) -> str:
        """"2026-10-08T05:12:00.000Z" ili lokalno vrijeme → "08.10. 07:12" (za poruke)."""
        try:
            when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return stamp or "?"
        return f"{(when.astimezone(self.tz) if when.tzinfo else when):%d.%m. %H:%M}"

    def _read_gap(self, state: State, src) -> None:
        """Čitanje stalo prije oglasa od prošlog pokretanja (Njuškalo: najviše stranica, stranica se
        nije učitala): sljedeće pokretanje jednom čita dublje od istog trenutka ("od:"). Ne zatvori
        li se ni tada, više se ne može (oglasi u praznini samo tonu niže): upozorenje s poveznicom za
        ručni pregled, a čitanje se nastavlja od sada. Daljnja nepročitana razdoblja prije nego što
        čitanje opet stigne do kraja skupljaju se i stižu u poruci kad stigne (ništa se ne preskače)."""
        key = f"{src.name}:praznina"
        more = f"praznine:{src.name}"
        row = next((h for h in state.health_all() if h["source"] == key), None)
        if not getattr(src, "incomplete", False) or not src.since:
            state.meta_set(f"od:{src.name}", "")
            if row and row.get("failures"):
                state.health_ok(key, self.stamp)
                periods = json.loads(state.meta_get(more) or "[]")
                state.meta_set(more, "[]")
                if row.get("alerted") and row["failures"] > 1:
                    links = "\n".join(f"{label}: {url}" for label, url in src.search_links())
                    self._alert_or_queue(
                        state, f"Scraper: {src.label} ponovno čita sve nove oglase",
                        f"Čitanje popisa ponovno stiže do oglasa od prošlog pokretanja ({self.stamp[:16].replace('T', ' ')})."
                        + (f"\n\nNakon prve poruke nisu pročitani ni oglasi objavljeni ili ponovno objavljeni "
                           f"{'; '.join(periods)} – pogledaj ih ručno:\n{links}" if periods else ""))
            return
        if not getattr(src, "catch_up", False):
            self.log(f"{src.label}: nije dočitano do oglasa od {src.since[:16]} – sljedeće pokretanje čita dublje")
            state.meta_set(f"od:{src.name}", src.since)
            return
        state.meta_set(f"od:{src.name}", "")
        period = f"od {self._local(src.since)} do {self._local(getattr(src, 'reached', '') or '')}"
        reason = getattr(src, "deep_error", "")
        self.log(f"{src.label}: oglasi {period} nisu pročitani ni dubljim čitanjem – nastavlja se od sada"
                 + (f" ({reason})" if reason else ""))
        _, alerted = state.health_fail(key, f"nepročitano {period}" + (f": {reason}" if reason else ""))
        if alerted:                     # već javljeno: razdoblje stiže u poruci kad čitanje opet stigne do kraja
            state.meta_set(more, json.dumps(json.loads(state.meta_get(more) or "[]")[-20:] + [period], ensure_ascii=False))
            return
        links = "\n".join(f"{label}: {url}" for label, url in src.search_links())
        self._alert_or_queue(
            state, f"Scraper: {src.label} – dio oglasa nije pročitan",
            f"{src.label}: oglasi objavljeni ili ponovno objavljeni {period} nisu pročitani – bilo ih je više nego što "
            "se čita u dva pokretanja" + (f" (dublje čitanje stalo: {reason})" if reason else "")
            + f". Među njima može biti nov oglas; pogledaj ih ručno:\n{links}\n\nAko se ponavlja, daljnja "
            "razdoblja stižu u jednoj poruci kad čitanje opet stigne do kraja; javi Claudeu.")
        state.mark_alerted(key)

    def _alert_or_queue(self, state: State, subject: str, text: str) -> None:
        """Jednokratno upozorenje (nema retka stanja koji bi ga ponovio): ne prođe li sad, čeka u
        meta "upozorenja" i šalje se sljedećih pokretanja (najviše 7 dana)."""
        if self._alert(subject, text) is False:
            queued = json.loads(state.meta_get("upozorenja") or "[]")
            state.meta_set("upozorenja", json.dumps(queued[-20:] + [{"naslov": subject, "tekst": text, "od": self.stamp}],
                                                    ensure_ascii=False))

    def _retry_alerts(self, state: State) -> None:
        try:
            queued = json.loads(state.meta_get("upozorenja") or "[]")
        except ValueError:
            queued = []
        if not queued:
            return
        oldest = (self.now - timedelta(days=UNSENT_DAYS)).isoformat(timespec="seconds")
        left = [a for a in queued if a.get("od", "") >= oldest and self._alert(a["naslov"], a["tekst"]) is False]
        state.meta_set("upozorenja", json.dumps(left, ensure_ascii=False))

    def _listing_errors(self, state: State, src, errors: list[str], failed: list[Listing]) -> None:
        """Oglasi koji se ne daju obraditi (greška u programu za neobičan oglas) ne stižu, a izvor
        "radi": nakon LISTING_ERROR_RUNS pokretanja zaredom upozorenje s poveznicama (jednom)."""
        key = f"{src.name}:obrada"
        row = next((h for h in state.health_all() if h["source"] == key), None)
        if not errors:
            if row and row.get("failures"):
                state.health_ok(key, self.stamp)
                if row.get("alerted"):
                    self._alert(f"Scraper: {src.label} – oglasi se ponovno obrađuju",
                                "Greška pri obradi oglasa više se ne javlja. Oglasi iz upozorenja ne stižu "
                                "naknadno – ako ih nisi pogledao, pogledaj ih ručno.")
            return
        failures, alerted = state.health_fail(key, errors[0][:300])
        if failures >= LISTING_ERROR_RUNS and not alerted and self._alert(
                f"Scraper: {src.label} – oglasi se ne daju obraditi",
                f"{src.label}: {plural(len(errors), 'oglas nije obrađen', 'oglasa nisu obrađena', 'oglasa nije obrađeno')} "
                f"(greška u programu), {failures} pokretanja zaredom. Ti oglasi ne stižu dok se greška ne popravi; "
                "pogledaj ih ručno:\n" + "\n".join(x.url for x in failed[:5])
                + f"\n\nGreška: {errors[0]}\n\nJavi Claudeu ovu poruku.") is not False:
            state.mark_alerted(key)

    def _detail_health(self, state: State, src) -> None:
        """Stranice oglasa ne rade dok popis radi (izvor je "ispravan"): captcha (Njuškalo) ili
        greška na svakoj otvorenoj stranici (promjena stranice). Oglasi tada čekaju ili stižu samo s
        podacima s popisa. Nakon DETAIL_ALERT_RUNS pokretanja zaredom upozorenje (jednom), i kad prođe."""
        key = f"{src.name}:oglasi"
        if getattr(src, "captcha_until", ""):
            state.meta_set(f"stanka:{src.name}", src.captcha_until)
        row = next((h for h in state.health_all() if h["source"] == key), None)
        blocked = getattr(src, "detail_blocked", False)
        broken = bool(getattr(src, "detail_failed", 0)) and not getattr(src, "detail_ok", False)
        if not blocked and not broken:
            # Prošlo je tek kad se neka stranica oglasa stvarno pročitala (pokretanje bez
            # ijednog otvaranja ne dokazuje ništa).
            if row and row.get("failures") and getattr(src, "detail_ok", False):
                state.health_ok(key, self.stamp)
                if row.get("alerted"):
                    self._alert(f"Scraper: {src.label} – stranice oglasa ponovno rade",
                                "Oglasi se ponovno otvaraju (površina, opis, lokacija).")
            return
        error = "captcha na stranicama oglasa" if blocked else f"stranice oglasa ne rade: {getattr(src, 'detail_error', '')}"
        failures, alerted = state.health_fail(key, error)
        if failures < DETAIL_ALERT_RUNS or alerted:
            return
        if blocked:
            subject = f"Scraper: {src.label} traži captchu na stranicama oglasa"
            text = (f"{src.label} {failures} pokretanja zaredom na stranicama oglasa vraća captchu (popis oglasa radi). "
                    "Novi oglasi čekaju do 18 pokretanja (oko 6 sati), zatim stižu samo s podacima s popisa (zemljište "
                    "bez površine, bez opisa). Obično prođe samo; ako potraje danima, javi Claudeu ovu poruku.")
        else:
            subject = f"Scraper: {src.label} – stranice oglasa ne rade"
            text = (f"{src.label} {failures} pokretanja zaredom ne može pročitati nijednu stranicu oglasa (popis oglasa "
                    f"radi). Zadnja greška: {getattr(src, 'detail_error', '')}\n\nNovi oglasi stižu kasnije i samo s "
                    "podacima s popisa (bez površine, opisa ili točne lokacije). Moguća promjena stranice – javi "
                    "Claudeu ovu poruku.")
        if self._alert(subject, text) is not False:
            state.mark_alerted(key)

    def _deep_health(self, state: State, src, done: bool) -> None:
        """Dnevno dublje čitanje (realestatecroatia) staje na ograničenju vremena ili na grešci i
        nastavlja se sljedeće pokretanje. Ne pročita li cijeli popis DEEP_ALERT_DAYS dana,
        upozorenje (jednom) – sniženja starijih oglasa ispod granice cijene tada se ne vide."""
        key = f"{src.name}:dubinsko"
        row = next((h for h in state.health_all() if h["source"] == key), None)
        error = getattr(src, "deep_error", "")
        if error:
            self.log(f"{src.label}: dublje čitanje stalo – {error}")
            state.meta_set(f"dubinsko_greska:{src.name}", error)
        if done:
            state.meta_set(f"dubinsko_greska:{src.name}", "")
            if row and row.get("failures"):
                state.health_ok(key, self.stamp)
                if row.get("alerted"):
                    self._alert(f"Scraper: {src.label} – dnevno dublje čitanje ponovno radi",
                                "Cijeli popis ponovno je pročitan: vide se i sniženja starijih oglasa ispod granice cijene.")
            return
        last = state.meta_get(f"dubinsko:{src.name}") or (state.meta_get(f"baseline:{src.name}") or self.stamp)[:10]
        try:
            days = (self.now.date() - datetime.fromisoformat(last[:10]).date()).days
        except ValueError:
            return
        if days <= DEEP_ALERT_DAYS:
            return
        error = state.meta_get(f"dubinsko_greska:{src.name}") or ""
        where = ", ".join(f"{k} od stranice {v}" for k, v in (getattr(src, "deep_reached", None) or {}).items())
        failures, alerted = state.health_fail(key, f"nije dočitano od {last[:10]}" + (f": {error}" if error else ""))
        if not alerted and self._alert(
                f"Scraper: {src.label} – dnevno dublje čitanje ne završava",
                f"{src.label}: dnevno dublje čitanje nije pročitalo cijeli popis od {last[:10]} (ostaje {where})."
                + (f"\nZadnja greška: {error}" if error else "")
                + "\n\nNovi oglasi i dalje stižu; ne vide se samo sniženja starijih oglasa ispod granice cijene. "
                  "Javi Claudeu ovu poruku.") is not False:
            state.mark_alerted(key)

    def _fresh_health(self, state: State, src) -> None:
        """Izvor "radi" (popis se čita), ali dugo ne donosi nijedan nov oglas – npr. portal ne
        poštuje redoslijed "najnoviji", pa se uvijek čitaju isti poznati oglasi. Bez ovoga bi izvor
        zauvijek bio "✅ radi". Upozorenje jednom (prag po izvoru: NEW_LISTING_DAYS)."""
        days = NEW_LISTING_DAYS.get(src.name)
        if days is None:
            return
        key = f"{src.name}:novi"
        stamps = [t for t in (state.newest(src.name), state.meta_get(f"baseline:{src.name}")) if self._age(t) is not None]
        if not stamps:
            return
        newest = min(stamps, key=self._age)
        row = next((h for h in state.health_all() if h["source"] == key), None)
        if self._age(newest) <= timedelta(days=days):
            if row and row.get("failures"):
                state.health_ok(key, self.stamp)
                if row.get("alerted"):
                    self._alert(f"Scraper: {src.label} – ponovno stižu novi oglasi",
                                f"{src.label} ponovno donosi nove oglase ({self.stamp[:16].replace('T', ' ')}).")
            return
        _, alerted = state.health_fail(key, f"zadnji nov oglas {newest[:16]}")
        links = "\n".join(f"{label}: {url}" for label, url in src.search_links())
        if not alerted and self._alert(
                f"Scraper: {src.label} – nema novih oglasa",
                f"{src.label} se čita bez greške, ali od {newest[:16].replace('T', ' ')} nije donio nijedan nov oglas "
                "(inače ih je više dnevno). Možda portal više ne poštuje redoslijed „najnoviji” ili je promijenio "
                f"pretragu. Usporedi ručno:\n{links}\n\nAko na portalu ima novijih oglasa, javi Claudeu ovu poruku.") is not False:
            state.mark_alerted(key)

    def _alert(self, subject: str, text: str) -> bool:
        """Upozorenje mailom; kad mail ne radi ili nije postavljen (Redmi), na Telegram. False
        kad slanje nije uspjelo nikamo (pozivatelj ga tada ponavlja sljedeći put)."""
        if self.email:
            if self.email_ok(subject, text):
                return True
            if not self.telegram:
                return False
        elif not self.telegram:
            if self.wants_telegram or self.wants_email:
                # Trebalo je stići, a nema kamo: ne smatra se poslanim (ponavlja se, a Redmijeva
                # upozorenja GitHub prosljeđuje mailom).
                self.log(f"(upozorenje nije poslano – nema ni maila ni Telegrama) {subject}")
                return False
            return self._email(subject, text)
        if len(text) > 3000:                 # Telegram prima najviše 4096 znakova
            text = text[:3000] + "…"
        try:
            self.telegram.send_text(f"⚠ <b>{html.escape(subject)}</b>\n{html.escape(text)}")
            return True
        except Exception as exc:  # noqa: BLE001
            self.log(f"Upozorenje nije poslano: {exc}")
            return False

    def email_ok(self, subject: str, text: str) -> bool:
        """Mail koji se smatra poslanim samo kad je stvarno otišao (bez postavki: False)."""
        return bool(self.email) and self._email(subject, text) is not False

    def _check_redmi(self, state: State) -> None:
        """Na GitHubu: javlja li se Redmi. Nakon svakog pokretanja Redmi šalje svoje stanje
        na granu state-redmi; ako zadnje pokretanje kasni, stiže mail (jednom). Razlikuje se
        "ne javlja se" (struja, Wi-Fi, Termux) od "pokreće se, ali ne završava" (prekid, greška);
        vrijeme s Redmija ispravlja se za odstupanje njegova sata."""
        path = Path(self.redmi_db)
        if not path.exists():
            return  # Redmi još nije postavljen
        if not self._redmi_usable():
            _, alerted = state.health_fail("redmi", "redmi.db je oštećen")
            if not alerted and self._alert(
                    "Scraper: stanje s Redmija je oštećeno",
                    "Datoteka redmi.db na grani state-redmi nije ispravna baza. Njuškalo se ne uspoređuje s ostalim "
                    "portalima dok Redmi ne pošalje ispravno stanje. Javi Claudeu ovu poruku.") is not False:
                state.mark_alerted("redmi")
            return
        other = State(path)
        last, started, code = other.meta_get("last_run"), other.meta_get("pocetak"), other.meta_get("kod") or ""
        try:
            skew = timedelta(seconds=float(other.meta_get("sat:razlika") or 0))
        except ValueError:
            skew = timedelta(0)
        rows = other.health_all()
        other.close()
        self._redmi_telegram(state, next((h for h in rows if h["source"] == "telegram"), None))
        self._redmi_relay(state, rows)
        self._redmi_code(state, code)
        if not last or self.now.hour < self.cfg["vrijeme"]["od_sata"] + 1:
            return
        limit = timedelta(minutes=self.cfg.get("nadzor", {}).get("redmi_kasni_minuta", 90))

        def age(stamp):                  # pravo vrijeme od zapisa s Redmija (njegov sat može griješiti)
            a = self._age(stamp) if stamp else None
            return a + skew if a is not None else None

        row = next((h for h in state.health_all() if h["source"] == "redmi"), None)
        if age(last) is not None and age(last) < -CLOCK_TOLERANCE:
            # Zapis iz budućnosti: Redmi bi izgledao živ i kad stane (sat nije izmjeren – stari kod).
            _, alerted = state.health_fail("redmi", f"sat na Redmiju žuri (zadnje pokretanje {last[:16]})")
            if not alerted and self._alert(
                    "Scraper: sat na Redmiju nije točan",
                    f"Redmi bilježi vrijeme u budućnosti (zadnje pokretanje {last[:16].replace('T', ' ')}), pa nadzor "
                    "Redmija ne radi dok se sat ne ispravi. Na Redmiju: Postavke → Dodatne postavke → Datum i vrijeme → "
                    "uključi automatsko vrijeme. Ako je već uključeno, javi Claudeu ovu poruku.") is not False:
                state.mark_alerted("redmi")
            return
        if age(last) is not None and age(last) <= limit:
            state.health_ok("redmi", self.stamp)
            if row and row.get("alerted"):
                self._alert("Scraper: Redmi se ponovno javlja", f"Redmi je ponovno pokrenuo scraper ({last[:16]}).")
            return
        state.health_fail("redmi", f"zadnje pokretanje {last[:16]}")
        if row and row.get("alerted"):
            return
        njuskalo = next((h for h in rows if h["source"] == "njuskalo"), None)
        read = njuskalo.get("last_ok") if njuskalo else None
        alive = [t for t in (started, read) if t and t > last and age(t) is not None and age(t) <= limit]
        when = last[:16].replace("T", " ")
        if alive:
            # Redmi radi i šalje stanje, ali pokretanje ne stiže do kraja (istek 15 min, greška pri kraju).
            fresh = read and age(read) is not None and age(read) <= limit
            subject = "Scraper: Redmi ne završava pokretanja"
            text = (f"Redmi pokreće scraper (zadnji početak {max(alive)[:16].replace('T', ' ')}), ali nijedno pokretanje "
                    f"nije završilo od {when}. "
                    + (f"Njuškalo se i dalje čita (zadnje čitanje {read[:16].replace('T', ' ')}), ali dio provjera "
                       "na kraju pokretanja ne radi. " if fresh else "Njuškalo se možda ne prati. ")
                    + "Na Redmiju u Ubuntuu upiši: tail -40 ~/scraper.log i pošalji Claudeu ispis.")
        else:
            subject = "Scraper: Redmi se ne javlja"
            text = (f"Redmi se nije javio od {when}. Dok se ne javi, Njuškalo se ne prati.\n\n"
                    "Provjeri je li Redmi uključen, na punjaču i na Wi-Fiju te radi li Termux "
                    "(obavijest „Termux” u traci obavijesti). Ako je sve u redu, javi Claudeu ovu poruku.")
        if self._alert(subject, text) is not False:
            state.mark_alerted("redmi")

    def _redmi_relay(self, state: State, rows: list[dict]) -> None:
        """Upozorenja Redmija (Njuškalo ne radi, captcha, nepročitani oglasi, sat) idu samo na
        njegov Telegram. Ne uspije li ih poslati (Telegram nije postavljen ili ne radi), ostanu
        nepotvrđena – tada ih GitHub prosljeđuje mailom (jednom), a i kad prođe."""
        limit = self.cfg.get("nadzor", {}).get("greske_prije_upozorenja", 3)
        thresholds = {"oglasi": DETAIL_ALERT_RUNS, "obrada": LISTING_ERROR_RUNS, "dubinsko": DEEP_ALERT_DAYS}
        mine = {h["source"]: h for h in state.health_all() if h["source"].startswith("redmi:")}
        for h in rows:
            if h["source"] in ("telegram", "github"):
                continue                     # Telegram javlja _redmi_telegram; GitHub sam sebe ne treba
            key = f"redmi:{h['source']}"
            row = mine.get(key)
            label = health_label(h["source"])
            base, _, suffix = h["source"].partition(":")
            needed = thresholds.get(suffix, 1) if suffix else (1 if base == "sat" else limit)
            recovered = (h.get("failures") or 0) < needed
            if recovered or h.get("alerted"):
                if row and row.get("failures") and (recovered or not row.get("alerted")):
                    state.health_ok(key, self.stamp)     # prošlo, ili je Redmi u međuvremenu sam javio
                    if recovered and row.get("alerted"):
                        self._alert(f"Scraper: Redmi – {label} ponovno u redu", f"Redmi javlja da je {label} ponovno u redu.")
                continue
            # Redmi je trebao javiti, a nije uspio: čeka se još jedno njegovo pokretanje.
            failures, alerted = state.health_fail(key, (h.get("last_error") or "")[:300])
            if failures >= 2 and not alerted and self._alert(
                    f"Scraper: Redmi javlja – {label}",
                    f"Redmi: {label} – {h.get('failures')} grešaka zaredom.\nZadnja greška: {h.get('last_error') or '—'}\n\n"
                    "Redmi to nije uspio poslati na Telegram, pa stiže odavde. Javi Claudeu ovu poruku.") is not False:
                state.mark_alerted(key)

    def _redmi_code(self, state: State, code: str) -> None:
        """Redmi kod osvježava s GitHuba pri svakom pokretanju. Ne uspije li (obrisana ili
        preimenovana grana, mreža), radi sa starim kodom bez poruke – a popravci ne stižu.
        Drukčiji kod nakon CODE_ALERT_RUNS GitHubovih pokretanja (~6 sati) → upozorenje."""
        mine = self._code_version()
        if not code or not mine:
            return
        row = next((h for h in state.health_all() if h["source"] == "redmi:kod"), None)
        if code.split()[0] == mine.split()[0]:
            if row and row.get("failures"):
                state.health_ok("redmi:kod", self.stamp)
                if row.get("alerted"):
                    self._alert("Scraper: Redmi ponovno radi s istim kodom kao GitHub", f"Kod: {mine[:7]}.")
            return
        failures, alerted = state.health_fail("redmi:kod", f"Redmi {code[:7]} {code[41:51]}, GitHub {mine[:7]} {mine[41:51]}")
        if failures >= CODE_ALERT_RUNS and not alerted and self._alert(
                "Scraper: Redmi radi sa starim kodom",
                f"Redmi već nekoliko sati radi s kodom {code[:7]} (od {code[41:51]}), a GitHub s {mine[:7]} (od "
                f"{mine[41:51]}), pa popravci ne stižu na Redmi. Na Redmiju u Ubuntuu upiši: cd ~/scraper && git "
                "status && git fetch --prune origin, i pošalji Claudeu ispis.") is not False:
            state.mark_alerted("redmi:kod")

    def _redmi_telegram(self, state: State, telegram: dict | None) -> None:
        """Redmi nema mail: kad on ne može slati na Telegram (npr. promijenjen bot ili razgovor
        na GitHubu, a ne i u ~/.scraper.env), javlja GitHub (mail, inače njegov Telegram) –
        jednom, i kad proradi."""
        row = next((h for h in state.health_all() if h["source"] == "redmi:telegram"), None)
        if not telegram or (telegram.get("failures") or 0) < 3:
            if row and row.get("failures"):
                state.health_ok("redmi:telegram", self.stamp)
                if row.get("alerted"):
                    self._alert("Scraper: Redmi ponovno šalje na Telegram", "Obavijesti s Njuškala ponovno stižu.")
            return
        if row and row.get("alerted"):
            return                       # već javljeno; čeka se oporavak (brojač ne raste svakim pokretanjem)
        error = telegram.get("last_error") or ""
        _, alerted = state.health_fail("redmi:telegram", error[:300])
        if not alerted and self._alert(
                "Scraper: Redmi ne može slati na Telegram",
                f"Redmi {telegram['failures']} pokretanja zaredom ne može ništa poslati na Telegram:\n{error}\n\n"
                "Obavijesti s Njuškala ne stižu (neposlane čekaju najviše 7 dana). Ako je mijenjan bot ili "
                "razgovor, iste vrijednosti (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID) upiši i u ~/.scraper.env na "
                "Redmiju (REDMI.md). Javi Claudeu ovu poruku.") is not False:
            state.mark_alerted("redmi:telegram")

    def _age(self, stamp) -> timedelta | None:
        """Koliko je prošlo od zapisanog vremena; None kad zapis nije ispravan (datoteka s
        drugog uređaja). Vrijeme bez zone je po zagrebačkom vremenu."""
        try:
            when = datetime.fromisoformat(stamp)
        except (TypeError, ValueError):
            return None
        return self.now - (when if when.tzinfo else when.replace(tzinfo=self.now.tzinfo))

    def _check_github(self, state: State) -> None:
        """Na Redmiju: radi li GitHub (github.json na grani state: početak i kraj zadnjeg
        pokretanja, zadnje pokretanje glavnog okidača). Ako kasni, poruka na Telegram (jednom) i
        poruka kad ponovno proradi – inače bi tišina izgledala kao "nema oglasa". Razlikuje:
        GitHub ne radi / radi samo rezerva (cron-job.org) / pokreće se, ali ne završava / Redmi ne
        preuzima stanje. Vrijeme se ispravlja za odstupanje sata na Redmiju."""
        info = self._github_info()
        last = info.get("zadnje_pokretanje")
        if not last or self.now.hour < self.cfg["vrijeme"]["od_sata"] + 2:
            return
        limit = timedelta(minutes=self.cfg.get("nadzor", {}).get("github_kasni_minuta", 120))
        row = next((h for h in state.health_all() if h["source"] == "github"), None)
        if self._age(last) is None:
            self.log(f"github.json: neispravno vrijeme zadnjeg pokretanja ({last!r:.40})")
            return

        def age(stamp):                  # pravo vrijeme (GitHubov sat je točan, Redmijev možda nije)
            a = self._age(stamp) if stamp else None
            return a - self.skew if a is not None else None

        if age(last) < -CLOCK_TOLERANCE:
            # GitHubovo vrijeme u budućnosti: sat na Redmiju kasni (nije izmjeren pri preuzimanju).
            self._clock_health(state, -age(last))
            return
        main, started = info.get("glavni_okidac") or last, info.get("pocetak") or last
        ok = lambda t: age(t) is not None and age(t) <= limit  # noqa: E731
        if ok(main) and ok(last):
            state.health_ok("github", self.stamp)
            if row and row.get("alerted"):
                titles = {"preuzimanje": "Scraper: Redmi ponovno preuzima stanje s GitHuba",
                          "rezerva": "Scraper: cron-job.org ponovno pokreće GitHub",
                          "kraj": "Scraper: GitHub ponovno završava pokretanja"}
                self._alert(titles.get(state.meta_get("github:upozorenje") or "", "Scraper: GitHub ponovno radi"),
                            f"Zadnje pokretanje na GitHubu: {last[:16].replace('T', ' ')}.")
            return
        _, alerted = state.health_fail("github", f"zadnje pokretanje {last[:16]}")
        if alerted:
            return
        # github.json se zamijeni pri svakom uspješnom preuzimanju: ako je star, ne preuzima Redmi.
        try:
            fetched = datetime.fromtimestamp(Path(self.seen_file).with_name("github.json").stat().st_mtime, self.tz)
        except OSError:
            fetched = None
        if ok(started) and not ok(main):
            kind, subject = "rezerva", "Scraper: cron-job.org ne pokreće GitHub"
            text = (f"cron-job.org nije pokrenuo scraper na GitHubu od {main[:16].replace('T', ' ')}; GitHub ga "
                    f"pokreće samo povremeno po svom rasporedu (zadnje {started[:16].replace('T', ' ')}). Portali osim "
                    "Njuškala ne čitaju se svakih 20 minuta. Provjeri na cron-job.org povijest pokretanja i je li "
                    "posao uključen (greška 401 ili 403: token za GitHub). Javi Claudeu ovu poruku.")
        elif ok(started):
            kind, subject = "kraj", "Scraper: GitHub ne završava pokretanja"
            text = (f"GitHub pokreće scraper (zadnji početak {started[:16].replace('T', ' ')}), ali nijedno pokretanje "
                    f"nije završilo od {last[:16].replace('T', ' ')}. Obavijesti mogu kasniti ili se ponoviti. Na "
                    "GitHubu → Actions pogledaj zadnja pokretanja (crvena ili prekinuta) i javi Claudeu ovu poruku.")
        elif fetched and self.now - fetched > limit:
            kind, subject = "preuzimanje", "Scraper: Redmi ne preuzima stanje s GitHuba"
            text = (f"Redmi zadnji put preuzeo stanje s GitHuba {fetched:%d.%m. u %H:%M} (zadnje poznato pokretanje "
                    f"na GitHubu {last[:16].replace('T', ' ')}). Dok ne proradi, poruke s Njuškala mogu se ponoviti. "
                    "Provjeri internet na Redmiju i GITHUB_TOKEN u ~/.scraper.env (zapis u ~/scraper.log), a na "
                    "githubstatus.com radi li GitHub; ako je sve u redu, javi Claudeu ovu poruku.")
        else:
            kind, subject = "github", "Scraper: GitHub ne radi"
            text = (f"GitHub nije pokrenuo scraper od {last[:16].replace('T', ' ')}. Dok ne proradi, ne prate se "
                    "portali osim Njuškala (Redmi radi). Provjeri cron-job.org (povijest pokretanja), na GitHubu → "
                    "Actions zadnja pokretanja i githubstatus.com; ako je sve u redu, javi Claudeu ovu poruku.")
        if self._alert(subject, text) is not False:
            state.mark_alerted("github")
            state.meta_set("github:upozorenje", kind)

    def review(self) -> Path:
        """Pregled: cijelo područje, bez obavijesti po oglasu i bez promjene stanja."""
        entries, sources = [], []
        state = State(self.db_path)
        prices = self._load_prices(state)        # procjena za "cijenu na upit"
        state.close()
        for src in self.enabled_sources():
            self.log(f"{src.label}: dohvat cijelog područja")
            try:
                listings = src.fetch(FULL, set())
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                sources.append({"label": src.label, "total": 0, "error": f"{type(exc).__name__}: {exc}",
                                "links": src.search_links()})
                continue
            decided = [(x, evaluate(x, self.criteria, self.locator, prices)) for x in listings]
            entries.extend(report.entry(x, d) for x, d in decided)
            sources.append(self._source_summary(src, decided))
            self.log(f"{src.label}: {len(listings)} oglasa")
        path = self._report("pregled", "Pregled oglasa", entries, sources,
                            note="Pregledni izvještaj: svi prikupljeni oglasi s odlukom i razlogom. "
                                 "Označi pogrešne kvačicom, dodaj napomenu i klikni „Kopiraj označene”.")
        path.with_suffix(".json").write_text(json.dumps({"sources": sources, "entries": entries}, ensure_ascii=False),
                                             encoding="utf-8")
        matching = sum(1 for e in entries if e["st"] in (PASS, WARN))
        self._send_report(path, f"<b>Pregled oglasa</b>: {len(entries)} oglasa, od toga {matching} odgovara "
                                "kriterijima (✅ i ⚠). Otvori datoteku u pregledniku.", "Scraper: pregled oglasa")
        return path

    def test(self) -> None:
        """Probna poruka na Telegram i probni mail."""
        ok = True
        if self.telegram:
            try:
                self.telegram.send_text("✅ <b>Scraper nekretnina</b>: Telegram radi. Ovdje će stizati novi oglasi.")
                self.log("Telegram: poruka poslana.")
            except Exception as exc:  # noqa: BLE001
                ok = False
                self.log(f"Telegram: GREŠKA {exc}")
        else:
            ok = False
            self.log("Telegram: nedostaju TELEGRAM_BOT_TOKEN ili TELEGRAM_CHAT_ID.")
        if self.email:
            try:
                self.email.send("Scraper nekretnina: probni mail",
                                "Mail radi. Ovdje će stizati tjedni izvještaj i prijave grešaka.")
                self.log("Mail: poslan.")
            except Exception as exc:  # noqa: BLE001
                ok = False
                self.log(f"Mail: GREŠKA {exc}")
        else:
            ok = False
            self.log("Mail: nedostaju SMTP_USER ili SMTP_PASSWORD.")
        if not ok:
            raise SystemExit(1)

    def _week(self) -> str:
        year, week, _ = self.now.isocalendar()
        return f"{year}-{week:02d}"

    def _retry_weekly(self, state: State) -> None:
        """Tjedni izvještaj šalje prvo redovno pokretanje u ponedjeljak (zasebno pokretanje u
        7:15 čekalo bi u redu iza pokretanja koje čeka gumbe, a takvo GitHub može otkazati);
        propušten ponedjeljak se nadoknađuje. Ako mail ne prođe, ponavlja se pri redovnim
        pokretanjima najviše dva dana; zatim upozorenje (i na Telegram) i stanka do sljedećeg
        tjedna."""
        if self.device != "github":
            return
        last = state.meta_get("tjedni:tjedan")
        if last == self._week() and state.meta_get("tjedni:neposlan"):
            state.meta_set("tjedni:neposlan", "")      # poslan u međuvremenu (naredba "tjedni")
            return
        if not state.meta_get("tjedni:neposlan") and last != self._week() \
                and state.meta_get("tjedni:odustao") != self._week() \
                and (self.now.weekday() == 0 or last is not None):
            state.conn.commit()
            try:
                if self.weekly(record=False):
                    state.meta_set("tjedni:tjedan", self._week())
                else:
                    state.meta_set("tjedni:neposlan", self.stamp)
            except Exception as exc:  # noqa: BLE001
                self.log(f"Tjedni izvještaj: GREŠKA {type(exc).__name__}: {exc}")
            return
        failed_at = state.meta_get("tjedni:neposlan")
        if not failed_at:
            return
        state.conn.commit()
        if self._age(failed_at) is not None and self._age(failed_at) > timedelta(days=2):
            if self._alert("Scraper: tjedni izvještaj nije poslan",
                           f"Tjedni izvještaj ({failed_at[:10]}) dva dana nije otišao mailom. Provjeri mail "
                           "(SMTP_USER, SMTP_PASSWORD) i javi Claudeu ovu poruku.") is not False:
                state.meta_set("tjedni:neposlan", "")
                state.meta_set("tjedni:odustao", self._week())   # do sljedećeg tjedna (ili naredbe "tjedni")
            return
        try:
            if self.weekly(record=False):
                state.meta_set("tjedni:neposlan", "")
                state.meta_set("tjedni:tjedan", self._week())
        except Exception as exc:  # noqa: BLE001
            self.log(f"Tjedni izvještaj: GREŠKA {type(exc).__name__}: {exc}")

    def _plan_decisions(self) -> "planwatch.Result | None":
        """Nove odluke o prostornim planovima (Službene novine PGŽ-a, Zavodov registar). Bez
        ponovnih pokušaja i s ograničenim trajanjem: izvještaj ide u redovnom pokretanju, a
        nedostupni poslužitelji ne smiju ga zadržati (neprovjereno stiže sljedeći tjedan)."""
        def get(url: str) -> str:
            raw = self.http.get(url, retries=0, timeout=PLAN_PAGE_SECONDS).content
            for enc in ("utf-8", "windows-1250"):
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    continue
            return raw.decode("utf-8", "replace")

        state = State(self.db_path)
        try:
            return planwatch.check(get, state, self.now.year, time.monotonic() + PLAN_CHECK_SECONDS)
        except Exception as exc:  # noqa: BLE001 – izvještaj ide i bez ovog dijela
            self.log(f"Provjera odluka o planovima nije uspjela: {exc}")
            return None
        finally:
            state.close()

    def _weekly_plans(self) -> "planwatch.Result | None":
        """Odluke o planovima čitaju se jednom tjedno: ponovno slanje izvještaja (mail nije
        prošao) koristi isto čitanje, a ne čita sn.pgz.hr i zavod.pgz.hr svakih 20 minuta."""
        state = State(self.db_path)
        try:
            cached = json.loads(state.meta_get("tjedni:planovi") or "{}")
            if cached.get("tjedan") == self._week():
                return planwatch.Result([planwatch.PlanDecision(**d) for d in cached["nove"]],
                                        cached["poznato"], cached["greske"], cached["izmjene"])
        except (ValueError, TypeError, KeyError):
            pass
        finally:
            state.close()
        plans = self._plan_decisions()
        if plans is not None:
            state = State(self.db_path)
            state.meta_set("tjedni:planovi", json.dumps(
                {"tjedan": self._week(), "nove": [dataclasses.asdict(d) for d in plans.new], "poznato": plans.known,
                 "greske": plans.errors, "izmjene": plans._updates}, ensure_ascii=False))
            state.close()
        return plans

    @staticmethod
    def _plan_section(plans: "planwatch.Result | None") -> str:
        e = html.escape
        head = "<h3>Nove odluke o prostornim planovima</h3>"
        if plans is None:
            return head + "<p>Provjera nije uspjela.</p>"
        items = "".join(f"<li>{e(d.jls)}: <a href='{e(d.url)}'>{e(d.title)}</a></li>" for d in plans.new)
        out = head + (f"<ul>{items}</ul><p>Ako odluka mijenja uvjete gradnje obiteljske kuće, treba "
                      f"ažurirati data/uvjeti_gradnje.yaml.</p>" if items
                      else f"<p>Nijedna (praćeno {plural(plans.known, 'odluka', 'odluke', 'odluka')} iz Službenih novina PGŽ-a i "
                           f"Zavodova registra).</p>")
        if plans.errors:
            out += "<p>Nije provjereno: " + e("; ".join(plans.errors)) + "</p>"
        return out

    def weekly(self, record: bool = True) -> bool:
        """Tjedni izvještaj mailom. Kad mail ne prođe, pamti se i pokušava ponovno pri
        sljedećim pokretanjima (record=False: poziva ga redovno pokretanje). Naredba
        "tjedni" (ručno ili stari okidač u 7:15) ne šalje ponovno izvještaj već poslan ovaj tjedan."""
        if record:
            state = State(self.db_path)
            done = state.meta_get("tjedni:tjedan") == self._week()
            state.close()
            if done:
                self.log("Tjedni izvještaj je ovaj tjedan već poslan.")
                return True
        since = (self.now - timedelta(days=7)).isoformat(timespec="seconds")
        counts, notified, near, health, dups = {}, [], [], [], []
        paths = [self.db_path] + ([self.redmi_db] if self._redmi_usable() else [])
        limit = timedelta(minutes=self.cfg.get("nadzor", {}).get("redmi_kasni_minuta", 90))
        for path in paths:  # stanje s GitHuba i, ako postoji, s Redmija (Njuškalo)
            state = State(path)
            counts.update(state.counts_since(since))
            notified += state.notified_since(since)
            near += state.near_misses_since(since)
            device = "Redmi – " if path != self.db_path else ""      # npr. Telegram s Redmija
            # Stanje s Redmija koji se dugo ne javlja je staro: ne smije pisati "✅ radi".
            last = state.meta_get("last_run") if device else None
            stale = bool(device) and (self._age(last) is None or self._age(last) > limit)
            health += [{**h, "uredjaj": device, "staro": last if stale else None,
                        "novi": state.newest(h["source"]) if h["source"] in NEW_LISTING_DAYS else None}
                       for h in state.health_all()]
            dups += state.duplicates_since(since)
            state.close()
        e = html.escape
        rows = "".join(
            f"<tr><td>{e(SOURCE_LABELS.get(s, s))}</td><td>{c.get(PASS, 0)}</td><td>{c.get(WARN, 0)}</td><td>{c.get(REJECT, 0)}</td></tr>"
            for s, c in sorted(counts.items())
        ) or "<tr><td colspan=4>nema novih oglasa</td></tr>"
        sent = "".join(
            f"<li><a href='{e(r['url'] or '')}'>{e(r['title'] or '')}</a> – {fmt_eur(r['price'])}, {e(r['jls'] or '')}</li>"
            for r in notified if not str(r["notified_at"]).startswith("zbirno")
        ) or "<li>nijedan</li>"
        nm = "".join(
            f"<li><a href='{e(r['url'] or '')}'>{e(r['title'] or '')}</a> – {e(', '.join(json.loads(r['reasons'] or '[]')))}</li>"
            for r in near
        ) or "<li>nijedan</li>"
        dl = "".join(
            f"<li><a href='{e(r['url'] or '')}'>{e(r['title'] or '')}</a> – {fmt_eur(r['price'])}, {e(r['jls'] or '')} "
            f"({e(SOURCE_LABELS.get(r['source'], r['source']))}; isti kao {e(str(r['notified_at'])[4:])})</li>"
            for r in dups[:100]
        ) or "<li>nijedan</li>"
        hl = "".join(
            f"<li>{e(h['uredjaj'] + health_label(h['source']))}: "
            + (f"❔ nepoznato – stanje s Redmija od {e((h['staro'] or '—')[:16].replace('T', ' '))}" if h["staro"]
               else "✅ radi" if not h["failures"] else f"⚠ {h['failures']} grešaka zaredom – {e(h['last_error'] or '')}")
            + f" (zadnji uspjeh: {e(h['last_ok'] or '—')}"
            + (f"; zadnji nov oglas: {e(h['novi'][:16].replace('T', ' '))}" if h["novi"] else "") + ")</li>"
            for h in health
        )
        body = f"""<h2>Tjedni izvještaj scrapera</h2>
<p>Razdoblje: {self.now - timedelta(days=7):%d.%m.} – {self.now:%d.%m.%Y.}</p>
<h3>Novi oglasi po izvoru</h3>
<table border=1 cellpadding=4 cellspacing=0><tr><th>Izvor</th><th>✅</th><th>⚠</th><th>❌</th></tr>{rows}</table>
<h3>Poslane obavijesti</h3><ul>{sent}</ul>
<h3>Za dlaku promašeni (cijena ili površina do {self.criteria.get('za_dlaku_posto', 15)} %)</h3><ul>{nm}</ul>
<h3>Preskočeni kao već viđeni ({len(dups)})</h3><p>Isti oglas na drugom portalu ili ponovno objavljen,
bez niže cijene.</p><ul>{dl}</ul>
<h3>Stanje izvora</h3><ul>{hl}</ul>"""
        plans = self._weekly_plans()
        body += self._plan_section(plans)
        text = "Tjedni izvještaj scrapera – otvori HTML verziju maila."
        subject = f"Scraper: tjedni izvještaj {self.now:%d.%m.%Y.}"
        # Bez postavki za mail izvještaj nije poslan (ponavlja se, nakon 2 dana upozorenje na Telegram).
        ok = self.email_ok(subject, text) if self.wants_email and not self.email else \
            self._email(subject, text, body) is not False
        if ok and plans:
            state = State(self.db_path)
            plans.save(state)
            state.close()
        self.log("Tjedni izvještaj poslan." if ok else "Tjedni izvještaj NIJE poslan – ponovno pri sljedećem pokretanju.")
        if record:
            state = State(self.db_path)
            state.meta_set("tjedni:neposlan" if not ok else "tjedni:tjedan", self.stamp if not ok else self._week())
            if ok:
                state.meta_set("tjedni:neposlan", "")
            state.close()
        return ok

