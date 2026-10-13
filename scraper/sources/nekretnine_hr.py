"""nekretnine.hr (grupa Indomio, isti oglasi kao Crozilla i Indomio).

Stranice s popisom imaju podatke u __NEXT_DATA__ (JSON), uključujući grad/općinu,
vrstu nekretnine, cijenu i površinu. Sortiranje: ?criterio=data&ordine=desc
(najnoviji), ?criterio=dataModifica&ordine=desc (nedavno izmijenjeni, npr. cijena).
Popis daje samo početak opisa (i stanje, parking, bazen iz polja ga4…); novi oglasi koji bi
mogli proći otvaraju se (props.pageProps.detailData): puni opis, stanje, parking, bazen,
godina izgradnje, okućnica (razdioba površina).
Oglas koji pokretanje ne stigne otvoriti čeka sljedeće pokretanje."""

import json
import re

from ..http import FetchError
from ..models import HOUSE, LAND, Listing
from ..text import fmt_eur, fmt_m2, fold, parse_number
from .base import DETAIL_RETRIES, FULL, Source

BASE = "https://www.nekretnine.hr"
COUNTY_SLUG = "primorsko-goranska-zupanija"
CATEGORIES = [
    ("prodaja-samostojeca-kuce", HOUSE, "samostojeće kuće"),
    ("prodaja-vikendice", HOUSE, "vikendice"),
    ("prodaja-zemljista", LAND, "zemljišta"),
]
_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
MAX_DETAILS = 10   # najviše otvorenih oglasa po pokretanju (ostali čekaju sljedeće)
_PARKING = re.compile(r"garaz|parkir|parking", re.I)
# Popis ima i polja za analitiku na talijanskom (ga4…): stanje, parking, značajke.
_CONDITIONS = {"da ristrutturare": "za renoviranje", "ottimo / ristrutturato": "odlično / renovirano",
               "nuovo / in costruzione": "novo / u izgradnji", "buono / abitabile": "dobro / useljivo"}


def _garage(text: str) -> str:
    """"3 posto auto" → "3" (broj mjesta), "1 in box privato/box in garage, 2 posto auto" →
    "garaža: 1, parkirnih mjesta: 2"."""
    parts = [("garaža" if "box" in what else "parkirnih mjesta", n)
             for n, what in re.findall(r"(\d+)\s+(posto auto|in box[^,]*)", text)]
    if len(parts) == 1 and parts[0][0] == "parkirnih mjesta":
        return parts[0][1]
    return ", ".join(f"{label}: {n}" for label, n in parts)


def jls_slug(name: str) -> str:
    return fold(name).replace(" ", "-")


def parse_page(html: str, kind: str) -> tuple[list[Listing], int]:
    """Oglasi sa stranice popisa i ukupan broj stranica."""
    m = _NEXT_DATA.search(html)
    if not m:
        raise ValueError("nekretnine.hr: na stranici nema __NEXT_DATA__")
    props = json.loads(m.group(1))["props"]["pageProps"]
    for query in props.get("dehydratedState", {}).get("queries", []):
        data = query.get("state", {}).get("data")
        if isinstance(data, dict) and isinstance(data.get("results"), list):
            listings = [_listing(r, kind) for r in data["results"] if r.get("realEstate")]
            return listings, int(data.get("maxPages") or 1)
    raise ValueError("nekretnine.hr: u podacima stranice nema popisa oglasa")


def _listing(result: dict, kind: str) -> Listing:
    re_ = result["realEstate"]
    prop = (re_.get("properties") or [{}])[0]
    loc = prop.get("location") or {}
    price = re_.get("price") or {}
    photo = (prop.get("photo") or {}).get("urls") or {}
    if not photo:
        photos = (prop.get("multimedia") or {}).get("photos") or []
        photo = photos[0].get("urls", {}) if photos else {}
    address = loc.get("address") or ""
    settlement = loc.get("macrozone") or (address.split(",")[0].strip() if "," in address else "")
    listing = Listing(
        source=NekretnineHr.name,
        source_id=str(re_["id"]),
        url=(result.get("seo") or {}).get("url") or f"{BASE}/oglasi/{re_['id']}/",
        title=re_.get("title") or "",
        kind=kind,
        subtype=(prop.get("typology") or {}).get("name", ""),
        price=price.get("value") if price.get("visible", True) else None,
        area=parse_number(prop.get("surface")),
        county=loc.get("province") or "",
        municipality=loc.get("city") or "",
        settlement=settlement,
        location_text=address,
        description=" ".join(filter(None, [prop.get("caption"), prop.get("description")])),
        image_url=photo.get("medium") or photo.get("large") or photo.get("small") or "",
    )
    listing.extra["opis_skracen"] = True   # popis daje samo početak opisa
    if "piscina" in [str(f).lower() for f in prop.get("ga4features") or []]:
        listing.extra["bazen"] = True
    condition = str(prop.get("ga4Condition") or "")
    if condition:
        listing.extra["stanje"] = _CONDITIONS.get(condition.lower(), condition)
    if prop.get("ga4Garage") and _garage(str(prop["ga4Garage"])):
        listing.extra["parking"] = _garage(str(prop["ga4Garage"]))
    # "marker": točna oznaka na karti; "only_area": samo područje; "no_map": bez karte.
    if loc.get("latitude") and loc.get("longitude") and loc.get("marker") != "no_map":
        listing.extra["lat"], listing.extra["lon"] = float(loc["latitude"]), float(loc["longitude"])
        listing.extra["priblizna_lokacija"] = loc.get("marker") != "marker"
    return listing


def parse_detail(html: str, listing: Listing) -> None:
    """Puni opis i značajke sa stranice oglasa."""
    m = _NEXT_DATA.search(html)
    if not m:
        raise ValueError("nekretnine.hr: na stranici oglasa nema __NEXT_DATA__")
    detail = json.loads(m.group(1))["props"]["pageProps"].get("detailData") or {}
    prop = ((detail.get("realEstate") or {}).get("properties") or [{}])[0]
    description = " ".join(filter(None, [prop.get("caption"), prop.get("description")]))
    if description:
        listing.description = description[:6000]
        listing.extra.pop("opis_skracen", None)
    primary = [f for f in prop.get("primaryFeatures") or [] if isinstance(f, dict) and f.get("value")]
    names = [str(f) for f in prop.get("features") or []] + [str(f.get("name")) for f in primary]
    parking = [n for n in names if _PARKING.search(fold(n))]
    if prop.get("garage"):                          # "1 u garaži", "3 na zajedničkom parkingu"
        listing.extra["parking"] = str(prop["garage"]).lower()
    elif parking:
        listing.extra["parking"] = parking[0].lower()
    if any(fold(n) == "bazen" for n in names) or any(f.get("codeName") == "pool" for f in primary):
        listing.extra["bazen"] = True
    if prop.get("condition"):                       # "Za renoviranje", "Dobro / Useljivo"
        listing.extra["stanje"] = str(prop["condition"])
    if prop.get("buildingYear"):
        listing.extra["godina_izgradnje"] = prop["buildingYear"]
    # Okućnica kuće: razdioba površina ("Stambeni prostor", "Vrt", "Zemljište").
    parts = (prop.get("surfaceConstitution") or {}).get("surfaceConstitutionElements") or []
    garden = [parse_number(e.get("surface")) for e in parts if isinstance(e, dict)
              and e.get("constitutionKey") in ("garden", "land")]
    land = parse_number(prop.get("land")) if prop.get("land") else max(filter(None, garden), default=None)
    if listing.kind == HOUSE and land and not listing.plot_area:
        listing.plot_area = land
    listing.extra["detalji"] = True


class NekretnineHr(Source):
    name = "nekretnine_hr"
    label = "nekretnine.hr"
    reopen_once = "polja-2026-10"   # stanje, parking, bazen, okućnica, puni opis (13. 10.)

    def reopen(self, row: dict) -> Listing | None:
        try:
            page = self.http.get(row["url"], retries=DETAIL_RETRIES).text
        except FetchError as exc:
            if str(exc).startswith(("HTTP 404", "HTTP 410")):
                return None
            raise
        m = _NEXT_DATA.search(page)
        detail = json.loads(m.group(1))["props"]["pageProps"].get("detailData") if m else None
        if not detail or not (detail.get("realEstate") or {}).get("properties"):
            raise ValueError("nekretnine.hr: na stranici oglasa nema podataka o oglasu")
        x = _listing({"realEstate": detail["realEstate"], "seo": {"url": row["url"]}}, row["kind"])
        parse_detail(page, x)
        return x

    def fetch(self, mode, known_ids):
        found: dict[str, Listing] = {}
        for category, kind, _ in CATEGORIES:
            if mode == FULL:
                for jls in self.included_names:
                    self._crawl(f"{BASE}/{category}/{jls_slug(jls)}/", kind, found, known_ids, max_pages=40, stop_on_known=False)
            else:
                # Dok ima novih (ujutro i nakon prekida ih je više), najviše 10 stranica.
                self._crawl(f"{BASE}/{category}/{COUNTY_SLUG}/", kind, found, known_ids, max_pages=10, stop_on_known=True)
                # Nedavno izmijenjeni oglasi (npr. snižena cijena): dok stranica ima nov oglas ili
                # promijenjenu cijenu (ujutro nakon noći ih je više od jedne stranice), najviše 10.
                self._crawl(f"{BASE}/{category}/{COUNTY_SLUG}/", kind, found, known_ids, max_pages=10,
                            stop_on_known=False, sort="dataModifica")
        if mode == FULL:
            return list(found.values())
        return self.open_details(found, known_ids,
                                 lambda x: parse_detail(self.http.get(x.url, retries=DETAIL_RETRIES).text, x), MAX_DETAILS)

    def _crawl(self, url, kind, found, known_ids, max_pages, stop_on_known, sort="data"):
        page = 1
        while page <= max_pages:
            resp = self.http.get(f"{url}?criterio={sort}&ordine=desc&pag={page}")
            listings, pages = parse_page(resp.text, kind)
            new = [x for x in listings if x.source_id not in known_ids and x.source_id not in found]
            changed = [x for x in listings if self.known_prices.get(x.source_id, "nov") != x.price]
            for x in listings:
                found.setdefault(x.source_id, x)
            if sort == "dataModifica":
                stop = page >= 2 and not changed      # izmijenjeni: dalje samo stariji, već viđeni
            else:
                stop = stop_on_known and not new
            if not listings or page >= pages or stop:
                break
            page += 1

    def search_links(self):
        links = []
        for category, kind, label in CATEGORIES:
            price, area = self.limits(kind)
            links.append((f"{label}, PGŽ, najnovije, do {fmt_eur(price)}, od {fmt_m2(area)}",
                          f"{BASE}/{category}/{COUNTY_SLUG}/?criterio=data&ordine=desc"
                          f"&prezzoMassimo={price}&superficieMinima={area}"))
        return links
