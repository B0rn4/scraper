"""gohome.hr – tražilica koja skuplja oglase s ~85 portala i agencija.

Iz nje se uzimaju samo oglasi s izvora koje ne pratimo izravno (npr. Njuškalo i
agencije). Pretraga je običnim jezikom ("kuca krk prodaja zadnjih 7 dana"), a
upit mora biti kodiran u ISO-8859-2. Izvorna adresa oglasa je base64 JSON u
parametru data poveznice RedirectTo(Real).aspx ili parametar izvor."""

import base64
import html
import json
import re
from urllib.parse import quote, unquote, urlparse

from ..models import HOUSE, LAND, Listing
from ..text import fold, parse_number
from .base import FULL, Source

BASE = "https://www.gohome.hr/nekretnine.aspx"
# Portali koje pratimo izravno – njihove oglase iz GoHomea preskačemo.
COVERED = {"nekretnine.hr", "indomio.hr", "crozilla.com", "index.hr", "oglasnik.hr", "vender.hr"}
CATEGORIES = [("kuca", HOUSE), ("gradevinsko zemljiste", LAND)]

_ITEM = re.compile(r'<div itemscope itemtype="http://schema.org/RealEstateListing" class="JQResult item" data="\{ id:\'(-?\d+)\' \}">')
_NAME = re.compile(r'<span itemprop="name">\s*([^<]+?)\s*</span>')
_PRICE = re.compile(r'<meta itemprop="price" content="(\d+)"')
_SOURCE = re.compile(r'<p class="source">\s*([^<]+?)\s*</p>')
_DESC = re.compile(r'<p itemprop="description" class="describe">\s*(.*?)\s*</p>', re.S)
_DATA = re.compile(r'RedirectTo(?:Real)?\.aspx\?data=([A-Za-z0-9_\-=]+)')
_IZVOR = re.compile(r'RedirectToReal\.aspx\?izvor=([^&"\'\s]+)')
_DATE = re.compile(r'<p itemprop="datePosted" class="indexed">\s*([^<]+?)\s*</p>')
_IMG = re.compile(r'<img[^>]+src="(https?://[^"]+)"')
_AREA = re.compile(r"([\d.]+(?:,\d+)?)\s*m2", re.I)
# GoHome sve iz pretrage "kuća" naziva "Kuća", i stanove. Prava vrsta se vidi iz adrese
# oglasa (".../kuca/...", ".../zemljiste/...", "...-stan-...") i prve rečenice opisa.
_FLAT_DESC = re.compile(r"\b(?:prodaj\w*|ponud\w*|predstavljamo)\b(?:(?!kuc)[^.]){0,40}?\bstan\b")
_SLUG_TYPES = [(re.compile(r"\bstan\b"), "stan"), (re.compile(r"\bdvojn"), "dvojna kuća"),
               (re.compile(r"\bu nizu\b|\bnizu\b"), "kuća u nizu")]
_LAND_SEGMENTS = {"zemljiste", "zemljista", "gradevinsko-zemljiste", "gradjevinsko-zemljiste"}


def _query_name(jls: str) -> str:
    # GoHome razumije nazive bez dijakritika; za Malinsku je dovoljno "malinska".
    return {"Malinska-Dubašnica": "malinska"}.get(jls, fold(jls))


def _source_url(block: str) -> str:
    for m in _DATA.finditer(block):
        data = m.group(1)
        try:
            url = json.loads(base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))).get("Izvor", "")
        except (ValueError, TypeError):
            continue
        if url:
            return url
    m = _IZVOR.search(block)
    return unquote(html.unescape(m.group(1))) if m else ""


def _classify(url: str, description: str, kind: str, subtype: str) -> tuple[str, str]:
    path = unquote(urlparse(url).path).lower().strip("/")
    segments = [fold(x).replace(" ", "-") for x in path.split("/")]
    words = fold(path)  # riječi iz adrese, bez crtica i kosih crta
    if kind == HOUSE and _LAND_SEGMENTS & set(segments[:-1]):
        return LAND, "Zemljište"
    if kind == LAND and "kuca" in segments[:-1]:
        return HOUSE, "Kuća"
    if kind == HOUSE:
        if _FLAT_DESC.search(fold(description)[:300]):
            return kind, "stan"
        for rx, label in _SLUG_TYPES:
            if rx.search(words):
                return kind, label
    return kind, subtype


def parse_page(page: str, kind: str) -> list[Listing]:
    out = []
    starts = [m.start() for m in _ITEM.finditer(page)] + [len(page)]
    for start, end in zip(starts, starts[1:]):
        block = page[start:end]
        gid = _ITEM.match(block).group(1)
        name = html.unescape((_NAME.search(block) or [None, ""])[1]) if _NAME.search(block) else ""
        domain = (_SOURCE.search(block).group(1) if _SOURCE.search(block) else "").removeprefix("www.")
        url = _source_url(block)
        if not name:
            continue  # poveznica na popis oglasa agencije, ne na oglas
        # Naslov: "Kuća, KRK, 495.000 €, 126,65 m2" – vrsta, mjesto, cijena, površina.
        parts = [p.strip() for p in name.split(",")]
        place = ", ".join(p for p in parts[1:] if p and not re.search(r"\d", p))
        area_m = _AREA.search(name)
        desc = html.unescape(re.sub(r"\s+", " ", _DESC.search(block).group(1))) if _DESC.search(block) else ""
        img = _IMG.search(block)
        item_kind, subtype = _classify(url, desc, kind, parts[0] if parts else "")
        out.append(Listing(
            source=GoHome.name,
            source_id=gid,
            url=url or f"https://www.gohome.hr/nekretnine.aspx?id={gid}",
            title=f"{name} ({domain})" if domain else name,
            kind=item_kind,
            subtype=subtype,
            price=parse_number(_PRICE.search(block).group(1)) if _PRICE.search(block) else None,
            area=parse_number(area_m.group(1)) if area_m else None,
            municipality=place.split(",")[0].title() if place else "",
            location_text=place,
            description=desc,
            image_url=img.group(1) if img else "",
            published=(_DATE.search(block).group(1).strip(" ,") if _DATE.search(block) else ""),
            extra={"izvor": domain},
        ))
    return out


class GoHome(Source):
    name = "gohome"
    label = "gohome.hr (Njuškalo i agencije)"
    interval_minutes = 120  # tražilica sama indeksira portale; češće nema smisla

    def fetch(self, mode, known_ids):
        period = "zadnjih 30 dana" if mode == FULL else "zadnjih 7 dana"
        max_pages = 6 if mode == FULL else 3
        found: dict[str, Listing] = {}
        for word, kind in CATEGORIES:
            for jls in self.included_names:
                q = f"{word} {_query_name(jls)} prodaja {period}"
                for page in range(1, max_pages + 1):
                    url = f"{BASE}?q={quote(q, encoding='iso-8859-2')}" + (f"&str={page}" if page > 1 else "")
                    text = self.http.get(url).content.decode("iso-8859-2", "replace")
                    items = parse_page(text, kind)
                    new = [x for x in items if x.source_id not in known_ids and x.source_id not in found]
                    for x in items:
                        if x.extra.get("izvor") not in COVERED:
                            found.setdefault(x.source_id, x)
                    if not items or (mode != FULL and not new) or f"str={page + 1}" not in text:
                        break
        return list(found.values())

    def search_links(self):
        return [(f"{word} {jls}", f"{BASE}?q={quote(f'{word} {_query_name(jls)} prodaja', encoding='iso-8859-2')}")
                for word, _ in CATEGORIES for jls in self.included_names[:3]]
