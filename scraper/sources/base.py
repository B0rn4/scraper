"""Zajednička sučelja izvora."""

from ..http import Http
from ..locations import Locator
from ..models import Listing

INCREMENTAL = "incremental"   # redovno pokretanje: samo najnoviji oglasi
FULL = "full"                 # pregled i početni popis: sve na području


class Source:
    name = ""          # ključ u konfiguraciji i bazi
    label = ""         # naziv za prikaz
    daily = False      # True: provjerava se jednom dnevno

    def __init__(self, http: Http, locator: Locator, criteria: dict):
        self.http = http
        self.locator = locator
        self.criteria = criteria

    def fetch(self, mode: str, known_ids: set[str]) -> list[Listing]:
        raise NotImplementedError

    def search_links(self) -> list[tuple[str, str]]:
        """Poveznice na iste pretrage na portalu, za usporedbu u izvještaju."""
        return []

    @property
    def included_names(self) -> list[str]:
        return [j.name for j in self.locator.jls.values() if j.included]

    def fetch_cap(self, mode: str, full_pages: int) -> int:
        return full_pages if mode == FULL else 3
