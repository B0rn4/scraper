"""nekretnine.hr (grupa Indomio, isti oglasi kao Crozilla i Indomio).

Stranice s popisom imaju podatke u __NEXT_DATA__ (JSON), uključujući grad/općinu,
vrstu nekretnine, cijenu i površinu. Sortiranje: ?criterio=data&ordine=desc
(najnoviji), ?criterio=dataModifica&ordine=desc (nedavno izmijenjeni, npr. cijena).
Popis daje samo početak opisa; novi oglasi koji bi mogli proći otvaraju se
(props.pageProps.detailData): puni opis, značajke (garaža, parking), godina izgradnje."""

import json
import re

from ..models import HOUSE, LAND, Listing
from ..text import fmt_eur, fmt_m2, fold, parse_number
from .base import DETAIL_RETRIES, FULL, Source, details_deadline, past

BASE = "https://www.nekretnine.hr"
COUNTY_SLUG = "primorsko-goranska-zupanija"
CATEGORIES = [
    ("prodaja-samostojeca-kuce", HOUSE, "samostojeće kuće"),
    ("prodaja-vikendice", HOUSE, "vikendice"),
    ("prodaja-zemljista", LAND, "zemljišta"),
]
_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
MAX_DETAILS = 10   # najviše otvorenih oglasa po pokretanju
_PARKING = re.compile(r"garaz|parkir|parking", re.I)


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
    names = [str(f) for f in prop.get("features") or []]
    names += [str(f.get("name")) for f in prop.get("primaryFeatures") or [] if isinstance(f, dict) and f.get("value")]
    parking = [n for n in names if _PARKING.search(fold(n))]
    if parking or (detail.get("trovakasa") or {}).get("boxAutoId"):
        listing.extra["parking"] = (parking[0] if parking else "garaža").lower()
    if prop.get("buildingYear"):
        listing.extra["godina_izgradnje"] = prop["buildingYear"]
    land = parse_number(prop.get("land")) if prop.get("land") else None
    if listing.kind == HOUSE and land and not listing.plot_area:
        listing.plot_area = land
    listing.extra["detalji"] = True


class NekretnineHr(Source):
    name = "nekretnine_hr"
    label = "nekretnine.hr"

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
        if mode != FULL:
            details, deadline = 0, details_deadline()
            for x in found.values():
                if details >= MAX_DETAILS or past(deadline):
                    break
                if x.source_id in known_ids or not self.worth_detail(x):
                    continue
                details += 1
                try:
                    parse_detail(self.http.get(x.url, retries=DETAIL_RETRIES).text, x)
                    self.detail_result()
                except Exception as exc:  # noqa: BLE001 – oglas ostaje s podacima s popisa
                    x.extra["detalji_greska"] = str(exc)[:200]
                    self.detail_result(f"{type(exc).__name__}: {exc}")
        return list(found.values())


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
