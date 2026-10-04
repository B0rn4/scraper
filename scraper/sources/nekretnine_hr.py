"""nekretnine.hr (grupa Indomio, isti oglasi kao Crozilla i Indomio).

Stranice s popisom imaju podatke u __NEXT_DATA__ (JSON), uključujući grad/općinu,
vrstu nekretnine, cijenu i površinu. Sortiranje: ?criterio=data&ordine=desc
(najnoviji), ?criterio=dataModifica&ordine=desc (nedavno izmijenjeni, npr. cijena)."""

import json
import re

from ..models import HOUSE, LAND, Listing
from ..text import fold, parse_number
from .base import FULL, Source

BASE = "https://www.nekretnine.hr"
COUNTY_SLUG = "primorsko-goranska-zupanija"
CATEGORIES = [
    ("prodaja-samostojeca-kuce", HOUSE, "samostojeće kuće"),
    ("prodaja-vikendice", HOUSE, "vikendice"),
    ("prodaja-zemljista", LAND, "zemljišta"),
]
_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


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
    return Listing(
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
                self._crawl(f"{BASE}/{category}/{COUNTY_SLUG}/", kind, found, known_ids, max_pages=3, stop_on_known=True)
                # Nedavno izmijenjeni oglasi (npr. snižena cijena).
                self._crawl(f"{BASE}/{category}/{COUNTY_SLUG}/", kind, found, known_ids, max_pages=1,
                            stop_on_known=False, sort="dataModifica")
        return list(found.values())

    def _crawl(self, url, kind, found, known_ids, max_pages, stop_on_known, sort="data"):
        page = 1
        while page <= max_pages:
            resp = self.http.get(f"{url}?criterio={sort}&ordine=desc&pag={page}")
            listings, pages = parse_page(resp.text, kind)
            new = [x for x in listings if x.source_id not in known_ids and x.source_id not in found]
            for x in listings:
                found.setdefault(x.source_id, x)
            if not listings or page >= pages or (stop_on_known and not new):
                break
            page += 1

    def search_links(self):
        links = []
        for category, _, label in CATEGORIES:
            for jls in self.included_names:
                links.append((f"{label} – {jls}", f"{BASE}/{category}/{jls_slug(jls)}/"))
        return links
