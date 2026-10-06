"""Glavni tok: dohvat, filter, obavijesti, izvještaji, nadzor izvora."""

import html
import json
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from . import dedupe, report, risks, tenders, watch
from .ispu import Ispu, check_land, gp_text
from .prices import AskingPrices, Ppv, land_note, land_short
from .db import State
from .filters import evaluate
from .http import Http
from .locations import Locator
from .models import LAND, PASS, REJECT, WARN, Decision, Listing
from .notify import SOURCE_LABELS, Email, Telegram, summary_text
from .sources import ALL
from .sources.base import FULL, INCREMENTAL
from .text import fmt_eur, fold

ROOT = Path(__file__).resolve().parent.parent
LAND_CHECK_SECONDS = 120   # najdulje trajanje provjera građevinskog područja po pokretanju
TENDER_CHECK_SECONDS = 240  # isto za čestice iz natječaja (jednom dnevno)


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
        self._ispu = None               # ISPU (građevinsko područje), otvara se kad zatreba
        self._place_names = {fold(n): n for j in self.locator.jls.values() for n in [j.name, *j.settlements]}
        self.criteria = self.cfg["kriteriji"]
        self.http = Http()
        notif = self.cfg.get("obavijesti", {})
        self.telegram = Telegram.from_env() if send and notif.get("telegram", True) else None
        self.email = Email.from_env() if send and notif.get("email", True) else None
        self.log_lines: list[str] = []

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

    def in_active_hours(self) -> bool:
        v = self.cfg["vrijeme"]
        return v["od_sata"] <= self.now.hour < v["do_sata"]

    def _email(self, subject: str, text: str, html_body: str = "", attachments=()) -> None:
        if not self.email:
            self.log(f"(mail nije poslan – nema postavki) {subject}")
            return
        try:
            self.email.send(subject, text, html_body, list(attachments))
        except Exception as exc:  # noqa: BLE001
            self.log(f"Slanje maila nije uspjelo: {exc}")

    def _report(self, name: str, title: str, entries: list[dict], sources: list[dict], note: str = "") -> Path:
        path = self.out_dir / f"{name}-{self.now:%Y-%m-%d-%H%M}.html"
        report.write(path, entries, title, f"{self.now:%d.%m.%Y. %H:%M}", sources, note)
        self.log(f"Izvještaj: {path} ({len(entries)} oglasa)")
        return path

    def _send_report(self, path: Path, caption: str, subject: str, mail: bool = False) -> None:
        """Izvještaj ide na Telegram; mail samo ako je izričito traženo (mail je za
        tjedni izvještaj i greške)."""
        if self.telegram:
            try:
                self.telegram.send_document(path, caption)
            except Exception as exc:  # noqa: BLE001
                self.log(f"Slanje izvještaja na Telegram nije uspjelo: {exc}")
        if mail:
            self._email(subject, caption.replace("<b>", "").replace("</b>", ""), attachments=[path])

    # --- naredbe ---

    def run(self, force: bool = False) -> None:
        """Redovno pokretanje (svakih 20 minuta)."""
        if not force and not self.in_active_hours():
            self.log(f"Izvan radnog vremena ({self.now:%H:%M}), ništa se ne radi.")
            return
        state = State(self.db_path)
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
                src.since = next((h["last_ok"] for h in state.health_all() if h["source"] == src.name), None)
                self.log(f"{src.label}: dohvat ({'početni, cijelo područje' if first else 'najnoviji'})")
                try:
                    listings = src.fetch(mode, state.known_ids(src.name))
                    if not listings and src.name != "fina":
                        raise RuntimeError("izvor nije vratio nijedan oglas (moguća promjena stranice)")
                except Exception as exc:  # noqa: BLE001
                    self._source_failed(state, src, exc)
                    continue
                self._source_ok(state, src)
                decided = []
                silent_baseline = first and not getattr(src, "baseline_report", True)
                for x in listings:
                    prev = state.get(x.key)
                    if prev:  # podaci sa stranice oglasa iz ranijeg dohvata (popis ih nema)
                        x.area = x.area or prev.get("area")
                        if not x.settlement and prev.get("settlement"):
                            x.settlement = prev["settlement"]
                            x.location_text = x.location_text or x.settlement
                    d = evaluate(x, self.criteria, self.locator)
                    if prev and d.notify and x.extra.get("opis_skracen") and prev.get("status") == REJECT:
                        d = self._keep_text_reject(d, prev)
                    old = state.upsert(x, d, self.stamp)
                    decided.append((x, d))
                    if silent_baseline or (old is None and x.extra.get("stari_oglas")):
                        # Bez obavijesti (početak praćenja ili stari oglas ponovno objavljen),
                        # ali zabilježeno – sniženje cijene kasnije i dalje stiže.
                        state.mark_notified(x.key, x.price, f"tiho:{self.stamp}")
                        continue
                    if not first:
                        headline = self._notify_reason(x, d, old)
                        if headline is not None:
                            headline = self._check_seen(state, seen, x, d, old, headline)
                        if headline is not None:
                            x.extra["ppv"] = self.ppv.note(x, d.jls)
                            x.extra["usporedba"] = prices.compare(x, d.jls) if prices else None
                            x.extra["cijena_kratko"] = [t for t in (prices.short(x, d.jls) if prices else None,
                                                                    self.ppv.short(x, d.jls)) if t]
                            to_notify.append((x, d, headline))
                counts = {s: sum(1 for _, d in decided if d.status == s) for s in (PASS, WARN, REJECT)}
                self.log(f"{src.label}: {len(listings)} oglasa – ✅ {counts[PASS]}, ⚠ {counts[WARN]}, ❌ {counts[REJECT]}")
                if first:
                    if not silent_baseline:
                        baseline.append((src, decided, ""))
                    state.meta_set(f"baseline:{src.name}", self.stamp)
                if src.daily:
                    state.meta_set(f"daily:{src.name}", today)
                state.conn.commit()

            if baseline:
                self._send_baseline(state, baseline)
            if len(to_notify) <= self.cfg.get("obavijesti", {}).get("max_poruka_po_pokretanju", 30):
                deadline = time.monotonic() + LAND_CHECK_SECONDS
                for x, d, _ in to_notify:
                    self._check_land(x, d, deadline)
            self._send_notifications(state, to_notify)
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
            state.meta_set("last_run", self.stamp)
            if self.redmi_db:
                self._check_redmi(state)
            if self.device == "github":
                dedupe.export(state, Path(self.db_path).with_name("seen.json.gz"))
        finally:
            state.close()

    @staticmethod
    def _keep_text_reject(d: Decision, prev: dict) -> Decision:
        """Oglas odbijen zbog rečenice iz punog opisa (npr. prodaje se suvlasnički dio) ostaje
        odbijen kad popis daje samo početak opisa – inače bi stiglo lažno "sad odgovara"."""
        labels = tuple(r.label for r in risks.RULES if r.reject)
        kept = [r for r in json.loads(prev.get("reasons") or "[]") if r.startswith(labels)]
        return Decision(REJECT, kept, jls=d.jls, location_evidence=d.location_evidence) if kept else d

    def _load_seen(self, state: State) -> dedupe.Seen:
        """Već viđeni oglasi: ova baza, baza s Redmija (na GitHubu) i sažetak s GitHuba (na Redmiju)."""
        seen = dedupe.Seen(self.locator)
        seen.add_state(state)
        if self.redmi_db and Path(self.redmi_db).exists():
            other = State(self.redmi_db)
            seen.add_state(other)
            other.close()
        try:
            seen.add_file(self.seen_file)
        except (OSError, ValueError) as exc:
            self.log(f"Sažetak viđenih oglasa nije učitan: {exc}")
        return seen

    def _check_land(self, x: Listing, d: Decision, deadline: float | None = None) -> None:
        """Zemljište: građevinsko područje i PPV na točnoj lokaciji (ISPU). Izvan
        građevinskog područja naselja → ⚠ (oglas i dalje stiže)."""
        if x.kind != LAND:
            return
        if deadline is not None and time.monotonic() > deadline:
            x.extra["gp"] = "🗺 Građevinsko područje: nije provjereno (vremensko ograničenje pokretanja)"
            return
        if self._ispu is None:
            self._ispu = Ispu()
        try:
            result = check_land(self._ispu, f"{x.title}. {x.description}", x.extra.get("lat"), x.extra.get("lon"),
                                bool(x.extra.get("priblizna_lokacija", True)), self._place_names)
        except Exception as exc:  # noqa: BLE001 – ISPU nije nužan za obavijest
            self.log(f"ISPU ({x.key}): {type(exc).__name__}: {exc}")
            x.extra["gp"] = "🗺 Građevinsko područje: nije provjereno (ISPU ne odgovara)"
            return
        x.extra["gp"] = result.line
        if result.warning:
            d.warnings.append(result.warning)
            if d.status == PASS:
                d.status = WARN
        info = result.info
        if info and info.land_values and x.price and x.area and x.price > 1000:
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
                failures, alerted = state.health_fail(name, f"{type(exc).__name__}: {exc}")
                self.log(f"{name}: GREŠKA ({failures}. dan zaredom): {exc}")
                if failures >= 3 and not alerted:
                    self._alert(f"Scraper: natječaji – {site['naziv']} ne rade",
                                f"Stranica {site['url']} tri dana zaredom vraća grešku:\n{exc}\n\nJavi Claudeu ovu poruku.")
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
            info = tenders.details(t.text) if t.text else {}
            published = t.published or t.extra.get("datum_iz_teksta", "")
            expired = info.get("rok") and info["rok"] < today
            # Prvi put: rok poznat i nije istekao (objava do pola godine stara), ili bez roka
            # objava iz zadnjih 45 dana.
            open_deadline = info.get("rok") and not expired and (not published or published >= oldest)
            if first and not open_deadline and (expired or not published or published < cutoff):
                state.tender_add(t, self.stamp, f"tiho:{self.stamp}")
                why = "rok istekao" if expired else "bez datuma i roka" if not published else f"objavljeno {published}"
                self.log(f"Natječaj bez poruke (prvo čitanje stranice, {why}): {t.title[:70]}")
                continue
            found = tenders.lots(t.text)
            if t.extra.get("regionalno"):     # PGŽ, CERP, Državne nekretnine: samo čestice na našem području
                found = [x for x in found if reader.area_of(f"{x.context} {x.ko}")]
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
                    else "samo stanovi/poslovni prostori" if len(t.text) >= tenders.MIN_TEXT and tenders.flats_only(t.text)
                    else f"popis naselja – {verdict[1]}" if verdict and verdict[0] == REJECT
                    else f"ne odgovara kriterijima – {misses}" if misses
                    else "ograničenje" if sent >= limit else "")
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
            except Exception as exc:  # noqa: BLE001
                failures, alerted = state.health_fail(name, f"{type(exc).__name__}: {exc}")
                self.log(f"{name}: GREŠKA ({failures}. dan zaredom): {exc}")
                if failures >= 3 and not alerted:
                    self._alert(f"Scraper: banke – {page['naziv']} ne radi",
                                f"Stranica {page['url']} tri dana zaredom vraća grešku:\n{exc}\n\nJavi Claudeu ovu poruku.")
                    state.mark_alerted(name)
                continue
            state.health_ok(name, self.stamp)
            stored = state.meta_get(key)
            known = set(json.loads(stored)) if stored else set()
            found, hashes = watch.changes(self.locator, body, known)
            if page.get("svaka_promjena"):        # najava (npr. novi oglasnik Butiga.hr): mail kod bilo koje promjene
                fresh = [s for s in watch.segments(body) if watch.digest(s) not in known]
                if stored is not None and fresh:
                    self._alert(f"Scraper: promjena na stranici {page['naziv']}",
                                f"{page['url']}\n\nNovo na stranici:\n" + "\n".join(fresh[:10])
                                + "\n\nJavi Claudeu ako je pokrenut novi oglasnik.")
                    self.log(f"{name}: promjena ({len(fresh)} novih odlomaka)")
                found = []
            if stored is not None and found:
                self.telegram.send_text(watch.format_change(page["naziv"], found), url=page["url"])
                self.log(f"{name}: novo s našim područjem ({len(found)})")
            state.meta_set(key, watch.dumps(hashes | known if len(known) < 5000 else hashes))
        state.meta_set("daily:banke", today)
        state.conn.commit()

    def _tender_message(self, t: tenders.Tender, info: dict, found: list[tenders.Lot], jls: str, where: str,
                        verdict: tuple[str, str] | None, prices: AskingPrices | None, deadline: float) -> str:
        """Poruka za natječaj s istim podacima kao za oglase: sažeti redak (more, Rijeka,
        Zagreb, cijena), naselje, za svaku česticu građevinsko područje (ISPU), početna
        cijena po m² prema PPV-u na lokaciji i medijanu traženih, upozorenja."""
        warnings = [verdict[1]] if verdict else []
        mjere, place = {}, ""
        row = self.locator.settlement_row(jls, "", where) if jls else None
        if row:
            r, exact = row
            mjere = {"naselje": r["naziv"], "tocno": exact, "more_km": r["more_km"], "rijeka_min": r["rijeka_min"],
                     "zagreb_min": r["zagreb_min"]}
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
            unit = lot.unit_price
            parts = []
            if point and point.land_values:
                low, high = min(point.land_values), max(point.land_values)
                if unit and not lot.house:
                    lot.notes.append(land_note(unit, low, high, f"na lokaciji, blok {point.block.title()}", "početna cijena"))
                    parts.append(land_short(unit, low, high))
                else:
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
                    lot.notes += [n for n in [prices.compare(x, jls)] if n]
                    parts.insert(0, prices.short(x, jls) or "")
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
            if self.redmi_db and Path(self.redmi_db).exists():
                other = State(self.redmi_db)
                rows += other.price_rows()
                other.close()
            prices = AskingPrices.from_rows(rows, self.locator, self.now)
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
        twins = seen.twins(new)
        if twins:
            cheapest = min(twins, key=lambda r: min(r["price"], r.get("notified_price") or r["price"]))
            low = min(cheapest["price"], cheapest.get("notified_price") or cheapest["price"])
            if x.price >= low * (1 - dedupe.PRICE_TOLERANCE):
                if old is None:
                    state.mark_notified(x.key, x.price, f"dup:{cheapest['key']}")
                self.log(f"Već viđen ({cheapest['key']}): {x.title[:60]}")
                return None
            if old is None:
                where = SOURCE_LABELS.get(cheapest["source"], cheapest["source"])
                headline = f"📉 Već viđen na {where} za {fmt_eur(low)} – sad jeftiniji"
        new["notified_at"], new["notified_price"] = self.stamp, x.price
        seen.add(new)  # drugi portal u istom pokretanju ne šalje isti oglas ponovno
        return headline

    def _notify_reason(self, x: Listing, d: Decision, old: dict | None) -> str | None:
        """Naslov obavijesti ili None ako se ne šalje ništa."""
        if not d.notify:
            return None
        if old is None:
            return ""
        old_price = old.get("price")
        if x.price and old_price and x.price < old_price - 1:
            change = f"{fmt_eur(old_price)} → {fmt_eur(x.price)}"
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
            self._send_report(path, f"<b>{len(to_notify)} novih oglasa</b> – previše za pojedinačne poruke, popis je u datoteci.",
                              "Scraper: puno novih oglasa", mail=False)
            for x, _, _ in to_notify:
                state.mark_notified(x.key, x.price, f"zbirno:{self.stamp}")
            return
        sent = 0
        for x, d, headline in to_notify:
            try:
                self.telegram.send_listing(x, d, headline)
                state.mark_notified(x.key, x.price, self.stamp)
                sent += 1
            except Exception as exc:  # noqa: BLE001
                self.log(f"Obavijest nije poslana ({x.key}): {exc}")
        state.conn.commit()
        self.log(f"Poslano obavijesti: {sent}/{len(to_notify)}")

    def _send_baseline(self, state: State, baseline) -> None:
        entries, sources = [], []
        for src, decided, _ in baseline:
            entries.extend(report.entry(x, d) for x, d in decided)
            sources.append(self._source_summary(src, decided))
            for x, d in decided:
                if d.notify:
                    state.mark_notified(x.key, x.price, f"zbirno:{self.stamp}")
        state.conn.commit()
        matching = sum(1 for e in entries if e["st"] in (PASS, WARN))
        names = ", ".join(s["label"] for s in sources)
        path = self._report("pocetni-popis", "Početni popis oglasa", entries, sources,
                            note="Prvo pokretanje izvora: ovo su svi trenutno aktivni oglasi na području. "
                                 "Od sada stižu samo novi oglasi i snižene cijene.")
        self._send_report(path, f"<b>Početni popis</b> ({names}): {matching} oglasa odgovara kriterijima "
                                f"(✅ i ⚠), ukupno pregledano {len(entries)}.", "Scraper: početni popis oglasa")

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
        if failures >= limit and not alerted:
            self._alert(
                f"Scraper: izvor {src.label} ne radi",
                f"Izvor {src.label} je {failures} puta zaredom vratio grešku.\n\nZadnja greška:\n{detail}\n\n"
                "Dok se ne popravi, s ovog izvora ne stižu obavijesti. Javi Claudeu ovu poruku.",
            )
            state.mark_alerted(src.name)

    def _source_ok(self, state: State, src) -> None:
        row = next((h for h in state.health_all() if h["source"] == src.name), None)
        was_alerted = bool(row and row.get("alerted"))
        state.health_ok(src.name, self.stamp)
        if was_alerted:
            self._alert(f"Scraper: izvor {src.label} ponovno radi", f"Izvor {src.label} ponovno radi ({self.stamp}).")

    def _alert(self, subject: str, text: str) -> None:
        """Upozorenje mailom; na Redmiju (bez postavki za mail) na Telegram."""
        if self.email or not self.telegram:
            self._email(subject, text)
            return
        try:
            self.telegram.send_text(f"⚠ <b>{html.escape(subject)}</b>\n{html.escape(text)}")
        except Exception as exc:  # noqa: BLE001
            self.log(f"Upozorenje nije poslano: {exc}")

    def _check_redmi(self, state: State) -> None:
        """Na GitHubu: javlja li se Redmi. Nakon svakog pokretanja Redmi šalje svoje stanje
        na granu state-redmi; ako zadnje pokretanje kasni, stiže mail (jednom)."""
        path = Path(self.redmi_db)
        if not path.exists():
            return  # Redmi još nije postavljen
        other = State(path)
        last = other.meta_get("last_run")
        other.close()
        if not last or self.now.hour < self.cfg["vrijeme"]["od_sata"] + 1:
            return
        limit = self.cfg.get("nadzor", {}).get("redmi_kasni_minuta", 90)
        row = next((h for h in state.health_all() if h["source"] == "redmi"), None)
        if self.now - datetime.fromisoformat(last) <= timedelta(minutes=limit):
            state.health_ok("redmi", self.stamp)
            if row and row.get("alerted"):
                self._email("Scraper: Redmi se ponovno javlja", f"Redmi je ponovno pokrenuo scraper ({last[:16]}).")
            return
        state.health_fail("redmi", f"zadnje pokretanje {last[:16]}")
        if not (row and row.get("alerted")):
            self._email(
                "Scraper: Redmi se ne javlja",
                f"Redmi se nije javio od {last[:16].replace('T', ' ')}. Dok se ne javi, Njuškalo se ne prati.\n\n"
                "Provjeri je li Redmi uključen, na punjaču i na Wi-Fiju te radi li Termux "
                "(obavijest „Termux” u traci obavijesti). Ako je sve u redu, javi Claudeu ovu poruku.",
            )
            state.mark_alerted("redmi")

    def review(self) -> Path:
        """Pregled: cijelo područje, bez obavijesti po oglasu i bez promjene stanja."""
        entries, sources = [], []
        for src in self.enabled_sources():
            self.log(f"{src.label}: dohvat cijelog područja")
            try:
                listings = src.fetch(FULL, set())
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                sources.append({"label": src.label, "total": 0, "error": f"{type(exc).__name__}: {exc}",
                                "links": src.search_links()})
                continue
            decided = [(x, evaluate(x, self.criteria, self.locator)) for x in listings]
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

    def weekly(self) -> None:
        """Tjedni izvještaj mailom."""
        since = (self.now - timedelta(days=7)).isoformat(timespec="seconds")
        counts, notified, near, health, dups = {}, [], [], [], []
        paths = [self.db_path] + ([self.redmi_db] if self.redmi_db and Path(self.redmi_db).exists() else [])
        for path in paths:  # stanje s GitHuba i, ako postoji, s Redmija (Njuškalo)
            state = State(path)
            counts.update(state.counts_since(since))
            notified += state.notified_since(since)
            near += state.near_misses_since(since)
            health += state.health_all()
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
            f"<li>{e(SOURCE_LABELS.get(h['source'], h['source']))}: "
            + ("✅ radi" if not h["failures"] else f"⚠ {h['failures']} grešaka zaredom – {e(h['last_error'] or '')}")
            + f" (zadnji uspjeh: {e(h['last_ok'] or '—')})</li>"
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
        text = "Tjedni izvještaj scrapera – otvori HTML verziju maila."
        self._email(f"Scraper: tjedni izvještaj {self.now:%d.%m.%Y.}", text, body)
        self.log("Tjedni izvještaj poslan.")
