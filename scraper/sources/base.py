"""Zajednička sučelja izvora."""

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
    # Čitanje stalo prije oglasa od prošlog pokretanja (najviše stranica, stranica se nije
    # učitala): runner tada ne pomiče "since" i sljedeće pokretanje čita dublje (catch_up).
    incomplete = False
    catch_up = False
    # Cijene već viđenih oglasa (postavlja runner): koliko daleko čitati "nedavno izmijenjene".
    known_prices: dict = {}
    # Jednom dnevno dublje čitanje (izvori kojima se sniženje inače ne vidi); runner postavlja deep.
    deep_daily = False
    deep = False

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

    def fetch(self, mode: str, known_ids: set[str]) -> list[Listing]:
        raise NotImplementedError

    def worth_detail(self, x: Listing) -> bool:
        """Stranica oglasa otvara se kad bi oglas mogao proći – i za zemljište na prihvatljivom
        mjestu kojem ne odgovaraju samo cijena ili površina: opis može spominjati parcelaciju,
        a tada stiže neovisno o njima."""
        d = evaluate(x, self.criteria, self.locator)
        if d.status != REJECT or d.near_miss:
            return True
        return x.kind == LAND and evaluate(x, self.criteria, self.locator, ignore_limits=True).status != REJECT

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
