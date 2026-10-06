"""burza.com.hr – regionalni oglasnik (Kvarner i Istra): agencije i privatni prodavači.

Popis: /oglasi/nekretnine-kuce-prodaja/<lokacija> i /oglasi/nekretnine-zemljista-prodaja/
<lokacija>, 20 oglasa po stranici (?stranica=N); na vrhu su plaćeni oglasi, zatim po
zadnjoj izmjeni. Popis daje naslov, cijenu i početak opisa; mjesto ("Lokacija"), puni
opis i datum zadnje izmjene su na stranici oglasa. Površina je samo u tekstu.

Početno stanje (FULL): popisi naših mjesta (mjesto iz filtra) i prve dvije stranice
cijelog Kvarnera i Istre (oglasi izvan naših popisa se otvore). Redovno: te dvije
stranice; novi oglasi se otvaraju (najviše MAX_DETAILS po pokretanju, ostali sljedeći
put). "Cijena na upit" se preskače."""

import html
import re

from ..models import HOUSE, LAND, Listing
from ..text import area_matches, fmt_eur, fold, parse_number
from .base import FULL, Source

BASE = "https://burza.com.hr"
REGION = "kvarner-i-istra"
KINDS = [("nekretnine-kuce-prodaja", HOUSE), ("nekretnine-zemljista-prodaja", LAND)]
# Filtri lokacija na portalu za naše područje → mjesto za prepoznavanje.
PLACES = {
    "kvarner-i-istra-crikvenica": "Crikvenica", "kvarner-i-istra-dramalj": "Dramalj",
    "kvarner-i-istra-jadranovo": "Jadranovo", "kvarner-i-istra-selce": "Selce", "kvarner-i-istra-kostrena": "Kostrena",
    "kvarner-i-istra-kraljevica": "Kraljevica", "kvarner-i-istra-matulji": "Matulji",
    "kvarner-i-istra-opatija-i-okolica": "Opatija", "kvarner-i-istra-otok-krk": "otok Krk",
    "kvarner-i-istra-rijeka": "Rijeka", "hrvatska-primorsko-goranska-lovran-lovran": "Lovran",
}
PAGE_SIZE = 20
MAX_DETAILS = 10
REGION_PAGES = (1, 2)
# Površina ispred koje piše ovo nije stambena površina kuće.
_NOT_LIVING = re.compile(r"okucnic|zemljist|parcel|vrt|dvorist|teras|balkon|garaz|okolis", re.I)


def _clean(value: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value or "")).split())


def _areas(text: str, kind: str) -> tuple[float | None, float | None]:
    """(površina, okućnica) iz teksta. Kuća: površina uz koju piše okućnica/zemljište
    nije stambena (prva takva je okućnica)."""
    area = plot = None
    for pos, value in area_matches(text):
        if value < 20:
            continue
        # Riječi ispred broja, samo iz istog dijela rečenice (ne preko prethodne površine).
        before = re.split(r"m2|m²|[,;!?]|\.\s", fold(text[max(0, pos - 40):pos]))[-1]
        if kind == HOUSE and _NOT_LIVING.search(before):
            if plot is None and re.search(r"okucnic|zemljist|parcel|dvorist|okolis", before):
                plot = value
            continue
        area = area or value
    return area, plot


def _set_area(x: Listing) -> None:
    """Površina iz naslova, inače iz opisa; okućnica kuće iz bilo kojeg."""
    title_area, title_plot = _areas(x.title, x.kind)
    text_area, text_plot = _areas(x.description, x.kind)
    x.area = title_area or text_area
    x.plot_area = title_plot or text_plot or x.plot_area


def parse_list(page: str, kind: str, place: str = "") -> list[Listing]:
    out = []
    for block in re.split(r'<div class="bad" ', page)[1:]:
        link = re.search(r'href="(/oglasi/[^"/]+/(\d+))"', block)
        if not link:
            continue
        title = re.search(r'class="bad-title"><a[^>]*>(.*?)</a>', block, re.S)
        price = re.search(r'class="price-primary">([^<]+)<', block)
        text = re.search(r'class="bad-text">(.*?)</p>', block, re.S)
        image = re.search(r'data-src="(https://static\.burza\.com\.hr/[^"]+)"', block)
        x = Listing(
            source=Burza.name,
            source_id=link.group(2),
            url=BASE + link.group(1),
            title=_clean(title.group(1)) if title else "",
            kind=kind,
            price=parse_number(price.group(1)) if price and re.search(r"\d", price.group(1)) else None,
            settlement=place if place and not place.startswith("otok") else "",
            location_text=place,
            description=_clean(text.group(1)) if text else "",
            image_url=image.group(1) if image else "",
        )
        x.extra["opis_skracen"] = True
        x.extra["samo_pgz"] = True          # regija obuhvaća i Istru i Liku: mjesto mora biti u PGŽ-u
        _set_area(x)
        out.append(x)
    return out


def parse_detail(page: str, x: Listing) -> None:
    """Mjesto, puni opis, površina iz teksta, datum zadnje izmjene, oglašivač."""
    place = re.search(r'Lokacija:</h5>.*?class="place-name">([^<]+)<', page, re.S)
    if place:
        x.settlement = _clean(place.group(1))
        x.location_text = x.settlement
    desc = re.search(r'<div class="bad-text[^"]*"[^>]*>(.*?)</div>', page, re.S)
    if desc:
        x.description = re.sub(r"^Opis:\s*", "", _clean(desc.group(1)))[:3000]
        x.extra.pop("opis_skracen", None)
    changed = re.search(r"Zadnja izmjena:\s*<strong>(\d{1,2})\.(\d{1,2})\.(\d{4})", page)
    if changed:
        x.published = f"{changed.group(3)}-{int(changed.group(2)):02d}-{int(changed.group(1)):02d}"
    advertiser = re.search(r"Podaci o oglašivaču\s*</[^>]+>\s*(?:<[^>]+>\s*)*([^<]{3,80})<", page)
    if advertiser:
        x.extra["oglasivac"] = _clean(advertiser.group(1))
    _set_area(x)


class Burza(Source):
    name = "burza"
    label = "burza.com.hr"
    baseline_report = False   # prvo pokretanje se samo zabilježi

    def _page(self, slug: str, location: str, page: int) -> str:
        return self.http.get(f"{BASE}/oglasi/{slug}/{location}" + (f"?stranica={page}" if page > 1 else "")).text

    def _list(self, slug: str, kind: str, location: str, place: str, pages) -> list[Listing]:
        out = []
        for page in pages:
            items = parse_list(self._page(slug, location, page), kind, place)
            out += [x for x in items if x.price]              # "cijena na upit" se preskače
            if len(items) < PAGE_SIZE:
                break
        return out

    def _detail(self, x: Listing) -> bool:
        try:
            parse_detail(self.http.get(x.url).text, x)
            return True
        except Exception as exc:  # noqa: BLE001
            x.extra["detalji_greska"] = str(exc)[:200]
            return False

    def fetch(self, mode, known_ids):
        found: dict[str, Listing] = {}
        if mode == FULL:
            # Naša mjesta i vrh cijele regije (Istra, općenita lokacija), da ih redovno
            # praćenje ne javi kao nove. Svaki se oglas otvori (točno naselje, puni opis);
            # ako stranica oglasa ne odgovori, ostaje mjesto iz filtra.
            for slug, kind in KINDS:
                for location, place in PLACES.items():
                    for x in self._list(slug, kind, location, place, range(1, 11)):
                        found.setdefault(x.source_id, x)
                for x in self._list(slug, kind, REGION, "", REGION_PAGES):
                    found.setdefault(x.source_id, x)
            out = []
            for x in found.values():
                if self._detail(x) or x.settlement or x.location_text:
                    out.append(x)
            return out
        for slug, kind in KINDS:
            for x in self._list(slug, kind, REGION, "", REGION_PAGES):
                found.setdefault(x.source_id, x)
        out, details = [], 0
        for x in found.values():
            if x.source_id in known_ids:                       # mjesto i površina iz ranijeg dohvata
                out.append(x)
            elif details < MAX_DETAILS:                        # ostali sljedeći put (bez mjesta bi bili "nepoznata lokacija")
                details += 1
                if self._detail(x):
                    out.append(x)
        return out

    def search_links(self):
        out = []
        for slug, kind in KINDS:
            price, _ = self.limits(kind)
            label = "kuće" if kind == HOUSE else "zemljišta"
            out.append((f"{label}, Kvarner i Istra, do {fmt_eur(price)} (površinu portal ne filtrira)",
                        f"{BASE}/oglasi/{slug}/{REGION}?pt={price}"))
        return out
