"""index.hr/oglasi – interni JSON API.

API traži kolačić koji stranica postavi pri prvoj posjeti, zato se prvo otvori
stranica kategorije. Lokacija se filtrira parametrima includeCountyIds i
includeCityIds (ID-jevi iz data/sources/index_locations_pgz.json).

Popis nema opis ni vrstu kuće/zemljišta. Zato se za nove oglase koji bi mogli proći
otvara i sam oglas (api/aditem/single-ad): opis ide kroz opasne izraze, a vrsta
odvaja dvojne kuće i poljoprivredno zemljište."""

import json
import re
from datetime import datetime
from pathlib import Path

from ..models import HOUSE, LAND, Listing
from ..text import fold
from .base import DETAIL_RETRIES, FULL, Source, details_deadline, past

BASE = "https://www.index.hr/oglasi"
CATEGORIES = [
    ("houses-for-sale", "prodaja-kuca", HOUSE),
    ("lands-for-sale", "prodaja-zemljista", LAND),
]
LOCATIONS = Path(__file__).resolve().parents[2] / "data" / "sources" / "index_locations_pgz.json"
JSON_HEADERS = {"Accept": "application/json", "Content-Type": "application/json"}
PAGE_SIZE = 24
INCREMENTAL_PAGES = 10
# Index drži dio Opatije kao zaseban "grad".
CITY_ALIASES = {"Opatija": ["Opatija", "Opatija - Okolica"]}
MAX_DETAILS = 10   # najviše otvorenih oglasa po pokretanju
# Šifre iz index.hr ui-config/hr/detail.json
HOUSE_TYPES = {1: "Samostojeća kuća", 2: "Dvojna kuća", 3: "Kuća u nizu", 4: "Stambeno-poslovna kuća"}
LAND_TYPES = {1: "Građevinsko zemljište", 2: "Poljoprivredno zemljište"}
PARKING_FIELDS = {"garage": "garaža", "garageSpace": "garažno mjesto", "enclosedCarPark": "natkriveno parkirno mjesto",
                  "noEnclosedCarPark": "vanjsko parkirno mjesto", "onSiteParking": "parking na licu mjesta"}


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
            # Popis je poredan po zadnjoj aktivnosti (objava, obnova); istaknuti su na vrhu.
            extra={"samo_popis": True,      # bez opisa i vrste – tek sa stranice oglasa
                   "istaknut": bool(x.get("isPromoted")),
                   "aktivnost": max(filter(None, [x.get("postedTime"), x.get("renewalTime")]), default="")},
        ))
    return out


def _time(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat((value or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def _year(value) -> int | None:
    m = re.match(r"(1[89]\d\d|20\d\d)", str(value or ""))
    return int(m.group(1)) if m else None


def parse_single(data: dict, listing: Listing) -> None:
    """Podaci iz samog oglasa: opis, vrsta kuće/zemljišta, okućnica, godine, parking, papiri."""
    ad = (data.get("data") or [{}])[0]
    listing.description = ad.get("description") or listing.description
    types = HOUSE_TYPES if listing.kind == HOUSE else LAND_TYPES if listing.kind == LAND else {}
    if ad.get("houseType" if listing.kind == HOUSE else "landType") in types:
        listing.subtype = types[ad.get("houseType" if listing.kind == HOUSE else "landType")]
    listing.area = listing.area or ad.get("area")
    if listing.kind == HOUSE and ad.get("gardenArea"):
        listing.plot_area = ad["gardenArea"]
    if ad.get("latitude") and ad.get("longitude"):
        listing.extra["lat"], listing.extra["lon"] = ad["latitude"], ad["longitude"]
        listing.extra["priblizna_lokacija"] = not ad.get("isPreciseLocation")
    for key, name in (("yearBuilt", "godina_izgradnje"), ("structuralRemodelYear", "godina_obnove")):
        if _year(ad.get(key)):
            listing.extra[name] = _year(ad.get(key))
    parking = [label for key, label in PARKING_FIELDS.items() if ad.get(key)]
    if isinstance(ad.get("numberOfParkingSpaces"), int) and ad["numberOfParkingSpaces"] > 0:
        parking.append(f"parkirnih mjesta: {ad['numberOfParkingSpaces']}")
    if parking:
        listing.extra["parking"] = ", ".join(parking)
    if ad.get("ownershipCertificate"):
        listing.extra["vlasnicki_list"] = True
    listing.extra["detalji"] = True
    listing.extra.pop("samo_popis", None)


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
        # Redovno: sljedeća stranica dok ima novih oglasa (ujutro i nakon prekida ih je više),
        # najviše INCREMENTAL_PAGES.
        max_pages = 80 if mode == FULL else INCREMENTAL_PAGES
        for category, category_hr, kind in CATEGORIES:
            page = 1
            while page <= max_pages:
                data = self._api(category, page)
                items = parse_items(data, category_hr, kind)
                if page == 1 and not items:   # kuća i zemljišta u PGŽ-u uvijek ima
                    raise RuntimeError(f"index.hr: kategorija {category_hr} je prazna (promjena stranice?)")
                new = [x for x in items if x.source_id not in known_ids and x.source_id not in found]
                for x in items:
                    found.setdefault(x.source_id, x)
                if not data.get("nextPage") or not data.get("data") or (mode != FULL and not new and not self._recent(items)):
                    break
                page += 1
        if mode != FULL:
            details, deadline = 0, details_deadline()
            for x in found.values():
                if details >= MAX_DETAILS or past(deadline):
                    break
                if x.source_id in known_ids or not self.worth_detail(x):
                    continue
                details += 1
                try:
                    parse_single(self.http.get(f"{BASE}/api/aditem/single-ad?code={x.source_id}&format=1",
                                               headers=JSON_HEADERS, retries=DETAIL_RETRIES).json(), x)
                except Exception as exc:  # noqa: BLE001 – oglas ostaje s podacima s popisa
                    x.extra["detalji_greska"] = str(exc)[:200]
        return list(found.values())

    def _recent(self, items: list[Listing]) -> bool:
        """Ima li i najstariji redovni oglas na stranici aktivnost nakon prošlog čitanja?
        Tada se čita i sljedeća stranica: obnovljeni (već poznati) oglasi mogu ispuniti
        cijelu stranicu i gurnuti nov oglas na sljedeću (ujutro, skupne obnove agencija)."""
        since = self.since_time()
        regular = [x for x in items if not x.extra.get("istaknut")]
        if since is None:
            return False
        if not regular:
            return True                  # samo istaknuti: redovni su tek na sljedećoj stranici
        times = [_time(x.extra.get("aktivnost")) for x in regular]
        return all(times) and min(times) >= since


    def search_links(self):
        return [
            ("kuće (u pretrazi odaberi Primorsko-goransku, cijenu i površinu)", f"{BASE}/nekretnine/prodaja-kuca"),
            ("zemljišta (u pretrazi odaberi Primorsko-goransku, cijenu i površinu)", f"{BASE}/nekretnine/prodaja-zemljista"),
        ]
