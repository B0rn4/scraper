"""Zajednička sučelja izvora."""

import copy
import time
from datetime import datetime, timedelta

from ..http import Http
from ..locations import Locator
from ..filters import evaluate
from ..models import HOUSE, LAND, REJECT, Listing

INCREMENTAL = "incremental"   # redovno pokretanje: samo najnoviji oglasi
FULL = "full"                 # pregled i početni popis: sve na području
MAX_ATTEMPTS = 3              # stranica oglasa ne odgovara 3 puta → oglas stiže s podacima s popisa
MAX_DEFERRALS = 18            # odgođen toliko pokretanja zaredom (~6 sati, noć se ne broji) → stiže s podacima s popisa
SINCE_MARGIN = timedelta(minutes=15)
# Otvaranje stranica oglasa: najviše toliko sekundi po izvoru i pokretanju, s jednim ponovnim
# pokušajem. Zaglavljene stranice oglasa inače produlje pokretanje preko ograničenja posla
# (45 min) i tada ne stigne ništa; ostali oglasi čekaju sljedeće pokretanje.
DETAIL_SECONDS = 240
DETAIL_RETRIES = 1


def details_deadline() -> float:
    return time.monotonic() + DETAIL_SECONDS


def past(deadline: float) -> bool:
    return time.monotonic() > deadline


class Source:
    name = ""          # ključ u konfiguraciji i bazi
    label = ""         # naziv za prikaz
    daily = False      # True: provjerava se jednom dnevno
    baseline_report = True  # False: prvo pokretanje se samo zabilježi, bez početnog popisa
    since: str | None = None  # vrijeme zadnjeg uspješnog dohvata (postavlja runner)
    # Stranice oglasa (runner ih prati u stanju izvora): captcha ili stanka nakon nje, barem
    # jedna stranica oglasa pročitana, i do kada traje stanka (runner je pamti).
    detail_blocked = False
    detail_ok = False
    captcha_until = ""
    # Stranica oglasa vratila grešku (ne captcha): koliko puta i zadnja greška. Kad sve otvorene
    # stranice oglasa pucaju više pokretanja zaredom, runner upozorava (promjena stranice?).
    detail_failed = 0
    detail_error = ""
    # Čitanje stalo prije oglasa od prošlog pokretanja (najviše stranica, stranica se nije
    # učitala): runner tada ne pomiče "since" i sljedeće pokretanje čita dublje (catch_up).
    incomplete = False
    catch_up = False
    reached = ""          # dokle je čitanje stiglo (najstariji pročitani oglas) kad je incomplete
    # Dublje čitanje (sustizanje, dnevno dublje) koje nije uspjelo: ne ruši izvor, runner ga prati.
    deep_error = ""
    # Cijene već viđenih oglasa (postavlja runner): koliko daleko čitati "nedavno izmijenjene".
    known_prices: dict = {}
    # Poznati oglasi koji nisu odbijeni, a nemaju površinu (početni popis ne otvara oglase;
    # postavlja runner): otvaraju se kad se pojave na popisu.
    known_incomplete: set = set()
    # Početak praćenja izvora (početni popis; postavlja runner): oglas objavljen prije toga, a
    # nepoznat, star je oglas koji je agencija obnovila – bilježi se bez poruke (stari_oglas).
    baseline_at = ""
    start_max_id: int | None = None   # najveći broj oglasa na početku praćenja (runner, State.start_max_id)
    # Jednom dnevno dublje čitanje (izvori kojima se sniženje inače ne vidi); runner postavlja deep.
    deep_daily = False
    deep = False
    # Jednokratni popravak: oznaka (npr. "vrsta-2026-10") – runner tada jednom ponovno otvara već
    # zapamćene oglase izvora (reopen) i tiho ih ocjenjuje ispočetka; nova oznaka = novi popravak.
    reopen_once = ""

    def __init__(self, http: Http, locator: Locator, criteria: dict):
        self.http = http
        self.locator = locator
        self.criteria = criteria
        self.pending: list[Listing] = []    # odgođeni u prošlim pokretanjima (postavlja runner)
        self.deferred: list[Listing] = []   # odgođeni u ovom dohvatu (runner ih sprema)

    def since_time(self) -> datetime | None:
        """Prošlo uspješno čitanje izvora (s 15 minuta zalihe), ili None."""
        try:
            return datetime.fromisoformat(self.since) - SINCE_MARGIN if self.since else None
        except ValueError:
            return None

    def add_pending(self, found: dict[str, Listing], known_ids: set[str]) -> None:
        """Oglasi odgođeni prošli put (previše novih za otvaranje ili stranica oglasa nije
        odgovorila) otvaraju se i kad ih popis ovaj put nema – novi oglasi su ih mogli
        pomaknuti iza pročitanih stranica."""
        waiting = {}
        for p in self.pending:
            if p.source_id in known_ids:
                continue
            x = found.get(p.source_id, p)      # svježi podaci s popisa, ako ga popis ima
            x.extra["pokusaja"] = max(x.extra.get("pokusaja", 0), p.extra.get("pokusaja", 0))
            x.extra["odgodjeno_puta"] = max(x.extra.get("odgodjeno_puta", 0), p.extra.get("odgodjeno_puta", 0))
            x.extra["greska_obrade"] = max(x.extra.get("greska_obrade", 0), p.extra.get("greska_obrade", 0))
            x.extra["odgodjen"] = True
            waiting[x.source_id] = x
        rest = {k: v for k, v in found.items() if k not in waiting}
        found.clear()
        found.update(waiting)                  # odgođeni se otvaraju prvi (najdulje čekaju)
        found.update(rest)

    def defer(self, x: Listing, failed: bool = False) -> bool:
        """Odgađa otvaranje oglasa za sljedeće pokretanje. False kad stranica oglasa nije
        odgovorila ni nakon MAX_ATTEMPTS pokušaja, ili je oglas odgođen MAX_DEFERRALS
        pokretanja zaredom – tada stiže s podacima s popisa. Broje se pokretanja, ne sati:
        oglas odgođen navečer ne smije ujutro stići neotvoren samo zato što je prošla noć."""
        x.extra["odgodjeno_puta"] = x.extra.get("odgodjeno_puta", 0) + 1
        if failed:
            x.extra["pokusaja"] = x.extra.get("pokusaja", 0) + 1
            if x.extra["pokusaja"] >= MAX_ATTEMPTS:
                return False
        if x.extra["odgodjeno_puta"] > MAX_DEFERRALS:
            return False
        self.deferred.append(x)
        return True

    def price_dropped(self, x: Listing) -> bool:
        """Poznat oglas s nižom cijenom od zapamćene: poruka o sniženju."""
        old = self.known_prices.get(x.source_id)
        return bool(old and x.price and x.price < old - 1)

    def reopen_known(self, x: Listing) -> bool:
        """Poznat oglas čija se stranica ipak otvara: snižena cijena ili zapamćen bez površine."""
        return self.price_dropped(x) or x.source_id in self.known_incomplete

    def open_details(self, found: dict[str, Listing], known_ids: set[str], opener, limit: int) -> list[Listing]:
        """Otvara stranice novih oglasa koji bi mogli proći, najviše limit po pokretanju (i do
        DETAIL_SECONDS). Ostali, i oni čija stranica nije odgovorila, čekaju sljedeće pokretanje
        (defer) – inače bi stigli samo s podacima s popisa (index.hr: bez opisa i vrste kuće ili
        zemljišta, pa bi npr. dvojna kuća prošla). Otvara se i poznat oglas sa sniženom cijenom ili
        bez površine (reopen_known): poruka o sniženju inače bi imala samo podatke s popisa (oglas
        zapamćen u početnom popisu, koji ne otvara oglase, nema ni površinu); on ne čeka – bez
        mjesta stiže kao prije."""
        self.add_pending(found, known_ids)
        out, details, deadline = [], 0, details_deadline()
        # Novi oglasi prvi, zatim stari obnovljeni, pa poznati (sniženje, bez površine): ne smiju
        # zauzeti mjesto novom.
        for x in sorted(found.values(), key=lambda x: (x.source_id in known_ids, bool(x.extra.get("stari_oglas")))):
            known = x.source_id in known_ids
            if (known and not self.reopen_known(x)) or not self.worth_detail(x):
                out.append(x)
                continue
            if details >= limit or past(deadline):
                if known or not self.defer(x):
                    out.append(x)      # čeka predugo: stiže s podacima s popisa
                continue
            details += 1
            try:
                opener(x)
                self.detail_result()
            except Exception as exc:  # noqa: BLE001 – pokušava se ponovno sljedeći put
                x.extra["detalji_greska"] = str(exc)[:200]
                self.detail_result(f"{type(exc).__name__}: {exc}")
                if not known and self.defer(x, failed=True):
                    continue
            out.append(x)
        return out

    def reopen(self, row: dict) -> Listing | None:
        """Već zapamćen oglas (redak iz baze) sa stranice oglasa, za reopen_once; None kad oglasa
        više nema."""
        raise NotImplementedError

    def detail_result(self, error: str = "") -> None:
        """Ishod otvaranja stranice oglasa (bez captche): runner prati jesu li sve pucale."""
        if error:
            self.detail_failed += 1
            self.detail_error = error[:200]
        else:
            self.detail_ok = True

    def fetch(self, mode: str, known_ids: set[str]) -> list[Listing]:
        raise NotImplementedError

    def worth_detail(self, x: Listing) -> bool:
        """Stranica oglasa otvara se kad bi oglas mogao proći – i za zemljište na prihvatljivom
        mjestu kojem ne odgovaraju samo cijena ili površina: opis može spominjati parcelaciju,
        a tada stiže neovisno o njima."""
        # Na kopiji: ocjena mijenja oglas (ruševina na građevinskom zemljištu postaje zemljište), a
        # stranica oglasa tek treba upisati površinu i okućnicu.
        d = evaluate(copy.deepcopy(x), self.criteria, self.locator)
        if d.status != REJECT or d.near_miss:
            return True
        # Odbijen samo kao ruševina: "za obnovu" ili građevinska dozvola često su tek u punom opisu.
        if x.kind == HOUSE and all(r.startswith("ruševina: „") for r in d.reasons):
            return True
        return x.kind == LAND and evaluate(copy.deepcopy(x), self.criteria, self.locator,
                                           ignore_limits=True).status != REJECT

    def search_links(self) -> list[tuple[str, str]]:
        """Poveznice na iste pretrage na portalu, za usporedbu u izvještaju i ručni pregled
        (gdje portal to podržava, s filtrom cijene i površine iz kriterija)."""
        return []

    def limits(self, kind: str) -> tuple[int, int]:
        """(najviša cijena, najmanja površina) iz kriterija za kuće ili zemljišta."""
        c = self.criteria["kuca" if kind == HOUSE else "zemljiste"]
        return int(c["max_cijena"]), int(c["min_povrsina"])

    @property
    def included_names(self) -> list[str]:
        return [j.name for j in self.locator.jls.values() if j.included]

    def fetch_cap(self, mode: str, full_pages: int) -> int:
        return full_pages if mode == FULL else 3
