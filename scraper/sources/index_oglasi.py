"""index.hr/oglasi – interni JSON API.

API traži kolačić koji stranica postavi pri prvoj posjeti, zato se prvo otvori
stranica kategorije. Lokacija se filtrira parametrima includeCountyIds i
includeCityIds (ID-jevi iz data/sources/index_locations_pgz.json)."""

import json
from pathlib import Path

from ..models import HOUSE, LAND, Listing
from ..text import fold
from .base import FULL, Source

BASE = "https://www.index.hr/oglasi"
CATEGORIES = [
    ("houses-for-sale", "prodaja-kuca", HOUSE),
    ("lands-for-sale", "prodaja-zemljista", LAND),
]
LOCATIONS = Path(__file__).resolve().parents[2] / "data" / "sources" / "index_locations_pgz.json"
JSON_HEADERS = {"Accept": "application/json", "Content-Type": "application/json"}
PAGE_SIZE = 24
# Index drži dio Opatije kao zaseban "grad".
CITY_ALIASES = {"Opatija": ["Opatija", "Opatija - Okolica"]}


def parse_items(data: dict, category_hr: str, kind: str) -> list[Listing]:
    out = []
    for x in data.get("data") or []:
        code = x.get("code") or x.get("id")
        images = x.get("images") or []
        summary = x.get("summary") or {}
        out.append(Listing(
            source=IndexOglasi.name,
            source_id=str(code),
            url=f"{BASE}/nekretnine/{category_hr}/oglas/{x.get('smartLink', '')}/{code}",
            title=x.get("title") or "",
            kind=kind,
            subtype="",
            price=x.get("price"),
            previous_price=x.get("previousPrice"),
            area=summary.get("area"),
            county=x.get("countyName") or "",
            municipality=x.get("cityName") or "",
            settlement=x.get("settlementName") or "",
            location_text=", ".join(filter(None, [x.get("settlementName"), x.get("cityName")])),
            image_url=f"{BASE}/api/image/direct/{images[0]}" if images else "",
            published=x.get("postedTime") or "",
        ))
    return out


class IndexOglasi(Source):
    name = "index_oglasi"
    label = "index.hr/oglasi"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        tree = json.loads(LOCATIONS.read_text(encoding="utf-8"))
        self.county_id = tree["id"]
        by_name = {fold(c["name"]): c["id"] for c in tree["children"]}
        self.city_ids = []
        for name in self.included_names:
            for alias in CITY_ALIASES.get(name, [name]):
                if fold(alias) in by_name:
                    self.city_ids.append(by_name[fold(alias)])
        self._warmed = False

    def _api(self, category: str, page: int) -> dict:
        if not self._warmed:
            self.http.get(f"{BASE}/nekretnine/prodaja-kuca")  # postavlja kolačić
            self._warmed = True
        params = (
            f"module=real-estate&category={category}&sortOption=4&itemPerPage={PAGE_SIZE}&page={page}"
            f"&includeCountyIds={self.county_id}" + "".join(f"&includeCityIds={c}" for c in self.city_ids)
        )
        return self.http.get(f"{BASE}/api/aditem?{params}", headers=JSON_HEADERS).json()

    def fetch(self, mode, known_ids):
        found: dict[str, Listing] = {}
        max_pages = 80 if mode == FULL else 2
        for category, category_hr, kind in CATEGORIES:
            page = 1
            while page <= max_pages:
                data = self._api(category, page)
                for x in parse_items(data, category_hr, kind):
                    found.setdefault(x.source_id, x)
                if not data.get("nextPage") or not data.get("data"):
                    break
                page += 1
        return list(found.values())

    def search_links(self):
        return [
            ("kuće (filtriraj na PGŽ u pretrazi)", f"{BASE}/nekretnine/prodaja-kuca"),
            ("zemljišta (filtriraj na PGŽ u pretrazi)", f"{BASE}/nekretnine/prodaja-zemljista"),
        ]
