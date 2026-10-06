"""Zajednička sučelja izvora."""

from ..http import Http
from ..locations import Locator
from ..models import HOUSE, Listing

INCREMENTAL = "incremental"   # redovno pokretanje: samo najnoviji oglasi
FULL = "full"                 # pregled i početni popis: sve na području
MAX_ATTEMPTS = 3              # stranica oglasa ne odgovara 3 puta → oglas stiže s podacima s popisa


class Source:
    name = ""          # ključ u konfiguraciji i bazi
    label = ""         # naziv za prikaz
    daily = False      # True: provjerava se jednom dnevno
    baseline_report = True  # False: prvo pokretanje se samo zabilježi, bez početnog popisa
    since: str | None = None  # vrijeme zadnjeg uspješnog dohvata (postavlja runner)

    def __init__(self, http: Http, locator: Locator, criteria: dict):
        self.http = http
        self.locator = locator
        self.criteria = criteria
        self.pending: list[Listing] = []    # odgođeni u prošlim pokretanjima (postavlja runner)
        self.deferred: list[Listing] = []   # odgođeni u ovom dohvatu (runner ih sprema)

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
            x.extra["odgodjen"] = True
            waiting[x.source_id] = x
        rest = {k: v for k, v in found.items() if k not in waiting}
        found.clear()
        found.update(waiting)                  # odgođeni se otvaraju prvi (najdulje čekaju)
        found.update(rest)

    def defer(self, x: Listing, failed: bool = False) -> bool:
        """Odgađa otvaranje oglasa za sljedeće pokretanje. False kad stranica oglasa nije
        odgovorila ni nakon MAX_ATTEMPTS pokušaja – tada oglas stiže s podacima s popisa."""
        if failed:
            x.extra["pokusaja"] = x.extra.get("pokusaja", 0) + 1
            if x.extra["pokusaja"] >= MAX_ATTEMPTS:
                return False
        self.deferred.append(x)
        return True

    def fetch(self, mode: str, known_ids: set[str]) -> list[Listing]:
        raise NotImplementedError

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
