"""oglasnik.hr (Plavi oglasnik) – Next.js stranica s podacima o oglasima u
ugrađenom RSC sadržaju (self.__next_f.push). Filter lokacije: f[4][<id>]=true,
4559 = Primorsko-goranska županija."""

import json
import re

from ..models import HOUSE, LAND, Listing
from ..text import fmt_eur, fmt_m2, fold, parse_number
from .base import FULL, Source

BASE = "https://oglasnik.hr"
PGZ_LOCATION_ID = 4559
CATEGORIES = [("kuce-prodaja", HOUSE), ("zemljista-prodajem", LAND)]
_PUSH = re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', re.S)
_AD_START = re.compile(r'"ad":\{"id":(\d+)')
_TEXT_CHUNK = re.compile(rb"(?:^|\n)([0-9a-f]+):T([0-9a-f]+),")
_HREF = re.compile(r'href="(/(?:kuce-prodaja|zemljista-prodajem)/[^"]*?-oglas-(\d+))"')


def rsc_payload(html: str) -> str:
    return "".join(json.loads('"' + c + '"') for c in _PUSH.findall(html))


def _text_chunks(payload: str) -> dict[str, str]:
    """Dugi tekstovi (opisi) su u RSC-u izdvojeni kao "<id>:T<duljina u bajtovima>,<tekst>"."""
    raw = payload.encode("utf-8")
    chunks = {}
    for m in _TEXT_CHUNK.finditer(raw):
        length = int(m.group(2), 16)
        chunks[m.group(1).decode()] = raw[m.end(): m.end() + length].decode("utf-8", "replace")
    return chunks


def _params(ad: dict) -> list[dict]:
    params = [p for group in ad.get("details") or [] for p in group.get("params") or []]
    return params or list(ad.get("list") or [])


def parse_page(html: str, kind: str) -> list[Listing]:
    payload = rsc_payload(html)
    texts = _text_chunks(payload)
    hrefs = {ad_id: href for href, ad_id in _HREF.findall(html)}
    decoder = json.JSONDecoder()
    ads: dict[str, dict] = {}
    for m in _AD_START.finditer(payload):
        if m.group(1) in ads:
            continue
        try:
            ad, _ = decoder.raw_decode(payload, m.start() + len('"ad":'))
        except ValueError:
            continue
        ads[m.group(1)] = ad
    return [_listing(ad, kind, texts, hrefs) for ad in ads.values()]


def _listing(ad: dict, kind: str, texts: dict, hrefs: dict) -> Listing:
    ad_id = str(ad["id"])
    names = [loc.get("name", "") for loc in ad.get("location") or []]
    county, city, settlement = (names + ["", "", "", ""])[1:4]
    params = _params(ad)

    def param(*slugs):
        for p in params:
            if p.get("slug") in slugs:
                return p.get("value")
        return None

    if kind == HOUSE:
        subtype = param("re_house_type") or ""
        area = parse_number(param("re_living_area"))
        plot = parse_number(param("re_infield_area"))
    else:
        subtype = next((p.get("value") for p in params if "type" in (p.get("slug") or "")), "") or ""
        area = next((parse_number(p.get("value")) for p in params if "area" in (p.get("slug") or "")), None)
        plot = None
    description = ad.get("description") or ""
    if description.startswith("$"):
        description = texts.get(description[1:], "")
    category = (ad.get("category") or {}).get("url") or ("kuce-prodaja" if kind == HOUSE else "zemljista-prodajem")
    href = hrefs.get(ad_id) or f"/{category}/{fold(ad.get('title', '')).replace(' ', '-')}-oglas-{ad_id}"
    media = ad.get("media") or []
    return Listing(
        source=Oglasnik.name,
        source_id=ad_id,
        url=BASE + href,
        title=ad.get("title") or "",
        kind=kind,
        subtype=subtype,
        price=parse_number((ad.get("price") or {}).get("value")),
        area=area,
        plot_area=plot,
        county=county,
        municipality=city,
        settlement=settlement,
        location_text=", ".join(filter(None, [settlement, city])),
        description=description,
        image_url=_absolute((media[0].get("listing") or media[0].get("thumb") or "") if media else ""),
        published=ad.get("publish") or "",
    )


def _absolute(url: str) -> str:
    return f"https://www.oglasnik.hr{url}" if url.startswith("/") else url


class Oglasnik(Source):
    name = "oglasnik"
    label = "oglasnik.hr"

    def fetch(self, mode, known_ids):
        found: dict[str, Listing] = {}
        max_pages = 40 if mode == FULL else 5       # redovno: dok ima novih (ujutro, nakon prekida)
        for category, kind in CATEGORIES:
            page = 1
            while page <= max_pages:
                url = f"{BASE}/{category}?sort=newest&page={page}&f%5B4%5D%5B{PGZ_LOCATION_ID}%5D=true"
                listings = parse_page(self.http.get(url).text, kind)
                new = [x for x in listings if x.source_id not in known_ids and x.source_id not in found]
                for x in listings:
                    found.setdefault(x.source_id, x)
                if not listings or (mode != FULL and not new):
                    break
                page += 1
        return list(found.values())

    def search_links(self):
        # Filtri: f[2] cijena, f[45] stambena površina (kuće), f[44] ukupna površina (zemljišta).
        out = []
        for category, kind, label, area_id in (("kuce-prodaja", HOUSE, "kuće", 45), ("zemljista-prodajem", LAND, "zemljišta", 44)):
            price, area = self.limits(kind)
            out.append((f"{label}, PGŽ, najnovije, do {fmt_eur(price)}, od {fmt_m2(area)}",
                        f"{BASE}/{category}?sort=newest&f%5B4%5D%5B{PGZ_LOCATION_ID}%5D=true"
                        f"&f%5B2%5D%5Bmax%5D={price}&f%5B{area_id}%5D%5Bmin%5D={area}"))
        return out
