"""vender.hr – WordPress (Houzez) REST API: /wp-json/wp/v2/properties.

Filtri: property_state (županija), property_status (prodaja), property_type.
Cijena i površine su u property_meta (fave_property_price, fave_property_size,
fave_property_land), a grad i vrsta u pojmovima (_embed=wp:term)."""

import html
import re

from ..models import HOUSE, LAND, OTHER, Listing
from ..text import parse_number
from .base import FULL, Source

API = "https://vender.hr/wp-json/wp/v2/properties"
STATE_PGZ = 10350
STATUS_SALE = 32
PER_PAGE = 30
FIELDS = "id,date,link,title,content,property_type,property_meta,_links,_embedded"
HOUSE_TYPES = {62: "Kuća", 19277: "Samostojeća kuća", 19278: "Dvojna kuća", 19280: "Kuća u nizu",
               19251: "Vila", 20002: "Kuće", 19572: "Luksuzne vile", 19282: "Stambeno-poslovna kuća"}
LAND_TYPES = {19276: "Građevinsko zemljište", 120: "Zemljište", 20004: "Zemljišta", 19281: "Poljoprivredno zemljište"}
GENERIC = {"Kuća", "Kuće", "Zemljište", "Zemljišta"}
_TAGS = re.compile(r"<[^>]+>")
_TITLE_AREA = re.compile(r"(\d+(?:[.,]\d+)?)\s*m2", re.I)


def _meta(meta: dict, key: str):
    value = meta.get(key)
    if isinstance(value, list):
        value = value[0] if value else None
    return value


def parse_items(items: list[dict]) -> list[Listing]:
    out = []
    for x in items:
        terms = [t for group in (x.get("_embedded", {}).get("wp:term") or []) for t in group]
        type_ids = set(x.get("property_type") or [])
        if type_ids & HOUSE_TYPES.keys():
            kind, pool = HOUSE, HOUSE_TYPES
        elif type_ids & LAND_TYPES.keys():
            kind, pool = LAND, LAND_TYPES
        else:
            kind, pool = OTHER, {}
        types = [pool[i] for i in type_ids if i in pool]
        subtype = next((t for t in types if t not in GENERIC), types[0] if types else "")
        city = next((t["name"] for t in terms if t.get("taxonomy") == "property_city"), "")
        area_term = next((t["name"] for t in terms if t.get("taxonomy") == "property_area"), "")
        state = next((t["name"] for t in terms if t.get("taxonomy") == "property_state"), "")
        meta = x.get("property_meta") or {}
        title = html.unescape(_TAGS.sub("", (x.get("title") or {}).get("rendered", "")))
        price = parse_number(_meta(meta, "fave_property_price"))
        size = parse_number(_meta(meta, "fave_property_size"))
        land = parse_number(_meta(meta, "fave_property_land"))
        if kind == HOUSE and not size:
            m = _TITLE_AREA.search(title)
            size = parse_number(m.group(1)) if m else None
        media = (x.get("_embedded", {}).get("wp:featuredmedia") or [{}])[0]
        content = html.unescape(_TAGS.sub(" ", (x.get("content") or {}).get("rendered", "")))
        out.append(Listing(
            source=Vender.name,
            source_id=str(x["id"]),
            url=x.get("link") or "",
            title=title,
            kind=kind,
            subtype=subtype,
            price=price if price and price > 0 else None,
            area=size if kind == HOUSE else (land or size),
            plot_area=land if kind == HOUSE and land else None,
            county=state,
            municipality=city.title() if city.isupper() else city,
            settlement=area_term.title() if area_term.isupper() else area_term,
            location_text=_meta(meta, "fave_property_map_address") or "",
            description=" ".join(content.split())[:3000],
            image_url=media.get("source_url", "") if isinstance(media, dict) else "",
            published=x.get("date") or "",
        ))
        coords = re.match(r"\s*(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)", _meta(meta, "fave_property_location") or "")
        if coords and _meta(meta, "fave_property_map") == "1":
            # Oznaka na karti oglasa; agencija je može staviti i približno.
            out[-1].extra["lat"], out[-1].extra["lon"] = float(coords.group(1)), float(coords.group(2))
            out[-1].extra["priblizna_lokacija"] = False
    return out


class Vender(Source):
    name = "vender"
    label = "vender.hr"

    def fetch(self, mode, known_ids):
        types = ",".join(str(i) for i in [*HOUSE_TYPES, *LAND_TYPES])
        found: dict[str, Listing] = {}
        max_pages = 100 if mode == FULL else 1
        page = 1
        while page <= max_pages:
            # Puni zapis ima ~70 kB (SEO i statistika), pa se traže samo potrebna polja;
            # 100 oglasa po stranici nije stiglo u 40 s.
            url = (f"{API}?property_state={STATE_PGZ}&property_status={STATUS_SALE}&property_type={types}"
                   f"&orderby=date&order=desc&per_page={PER_PAGE}&page={page}&_fields={FIELDS}"
                   f"&_embed=wp:term,wp:featuredmedia")
            resp = self.http.get(url)
            for x in parse_items(resp.json()):
                found.setdefault(x.source_id, x)
            if page >= int(resp.headers.get("x-wp-totalpages") or 1):
                break
            page += 1
        return list(found.values())

    def search_links(self):
        return [("PGŽ, prodaja", "https://vender.hr/zupanija/primorsko-goranska/")]
