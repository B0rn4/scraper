"""vender.hr – WordPress (Houzez) REST API: /wp-json/wp/v2/properties.

Filtri: property_state (županija), property_status (prodaja), property_type.
Cijena i površine su u property_meta (fave_property_price, fave_property_size,
fave_property_land), a grad i vrsta u pojmovima (_embed=wp:term). Dodatne značajke agencije
(additional_features: "Tip kuće: dvojna", godina adaptacije, parkirna mjesta, površina parcele)
i oznake (property_feature: garaža, parkirno mjesto, bazen) dopunjuju vrstu i podatke."""

import html
import re

from .. import prikljucci
from ..http import FetchError
from ..models import HOUSE, LAND, OTHER, Listing
from ..text import fold, parse_number
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
# Dodatne značajke agencije (PHP-serijalizirano: naslov i vrijednost), npr. "Tip kuće": "dvojna".
_EXTRA_FEATURE = re.compile(r's:\d+:"fave_additional_feature_title";s:\d+:"(.*?)";'
                            r's:\d+:"fave_additional_feature_value";s:\d+:"(.*?)";', re.S)
_YEAR = re.compile(r"\b(1[89]\d\d|20\d\d)\b")


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
            area=(size if kind == HOUSE else (land or size)) or None,
            plot_area=land if kind == HOUSE and land else None,
            county=state,
            municipality=city.title() if city.isupper() else city,
            settlement=area_term.title() if area_term.isupper() else area_term,
            location_text=_meta(meta, "fave_property_map_address") or "",
            description=" ".join(content.split())[:3000],
            image_url=media.get("source_url", "") if isinstance(media, dict) else "",
            published=x.get("date") or "",
        ))
        try:
            _features(out[-1], meta, [t["name"] for t in terms if t.get("taxonomy") == "property_feature"])
        except Exception as exc:  # noqa: BLE001 – neobična značajka ne smije srušiti cijeli izvor
            out[-1].extra["detalji_greska"] = f"dodatne značajke: {type(exc).__name__}: {exc}"[:200]
        coords = re.match(r"\s*(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)", _meta(meta, "fave_property_location") or "")
        if coords and _meta(meta, "fave_property_map") == "1":
            # Oznaka na karti oglasa; agencija je može staviti i približno.
            out[-1].extra["lat"], out[-1].extra["lon"] = float(coords.group(1)), float(coords.group(2))
            out[-1].extra["priblizna_lokacija"] = False
    return out


def _features(x: Listing, meta: dict, features: list[str]) -> None:
    """Dodatne značajke ("Tip kuće", "Tip zemljišta", godine, parkirna mjesta, površina parcele),
    oznake (garaža, parkirno mjesto, bazen, priključci, vlasnički list, dozvole), godina izgradnje
    i "Stara cijena" ispred cijene."""
    extra = {html.unescape(k).strip().lower(): html.unescape(v).strip()
             for k, v in _EXTRA_FEATURE.findall(str(_meta(meta, "additional_features") or ""))}
    kind_type = extra.get("tip kuće" if x.kind == HOUSE else "tip zemljišta", "")
    words = fold(kind_type).split()          # "-" ili "/" (agencija upisuje slobodan tekst): ništa
    if x.kind in (HOUSE, LAND) and words and words[0] not in fold(x.subtype):
        x.subtype = f"{x.subtype} ({kind_type})" if x.subtype else kind_type   # npr. "Kuća (dvojna)"
    for name, key in (("godina izgradnje", "godina_izgradnje"), ("godina zadnje adaptacije", "godina_obnove"),
                      ("godina zadnje renovacije", "godina_obnove")):
        year = _YEAR.search(extra.get(name, ""))
        if year:
            x.extra[key] = int(year.group(1))
    year = _YEAR.search(str(_meta(meta, "fave_property_year") or ""))
    if year and "godina_izgradnje" not in x.extra:
        x.extra["godina_izgradnje"] = int(year.group(1))
    plot = parse_number(extra.get("površina parcele"))
    if x.kind == HOUSE and plot and not x.plot_area:
        x.plot_area = plot
    spaces = re.search(r"\d+", extra.get("parkirna mjesta", ""))
    marks = [f.lower() for f in features if re.search(r"(?i)garaž|parkir", f)]
    if spaces and int(spaces.group(0)) > 0:
        x.extra["parking"] = spaces.group(0)
    elif marks:
        x.extra["parking"] = ", ".join(marks)
    if any(re.search(r"(?i)\bbazen", f) for f in features):
        x.extra["bazen"] = True
    utilities = prikljucci.from_labels(features)
    if utilities:
        x.extra["prikljucci"] = utilities
    if any(fold(f) == "vlasnicki list" for f in features):
        x.extra["vlasnicki_list"] = True
    permits = [f.lower() for f in features if re.search(r"(?i)dozvol", f)]
    if permits:
        x.extra["dozvole"] = permits
    before = re.search(r"(?i)stara cijena:?\s*([\d.,]+)", str(_meta(meta, "fave_property_price_prefix") or ""))
    if before and parse_number(before.group(1)):
        x.previous_price = parse_number(before.group(1))


class Vender(Source):
    name = "vender"
    label = "vender.hr"
    reopen_once = "polja-2026-10"   # vrsta iz dodatnih značajki, parking, bazen, godine (13. 10.)

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
            items = parse_items(resp.json())
            if items and all(x.kind == OTHER for x in items):
                # Traže se samo kuće i zemljišta: portal je promijenio oznake vrsta.
                raise RuntimeError("vender.hr: nijedan oglas nije kuća ni zemljište (promjena vrsta?)")
            for x in items:
                found.setdefault(x.source_id, x)
            if page >= int(resp.headers.get("x-wp-totalpages") or 1):
                break
            page += 1
        return list(found.values())

    def reopen(self, row: dict) -> Listing | None:
        try:
            item = self.http.get(f"{API}/{row['source_id']}?_fields={FIELDS}&_embed=wp:term,wp:featuredmedia").json()
        except FetchError as exc:
            if str(exc).startswith(("HTTP 404", "HTTP 410")):
                return None
            raise
        return parse_items([item])[0] if isinstance(item, dict) and item.get("id") else None

    def search_links(self):
        return [("PGŽ, prodaja", "https://vender.hr/zupanija/primorsko-goranska/")]
