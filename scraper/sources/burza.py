"""burza.com.hr – regionalni oglasnik (Kvarner i Istra): agencije i privatni prodavači.

Popis: /oglasi/nekretnine-kuce-prodaja/<lokacija> i /oglasi/nekretnine-zemljista-prodaja/
<lokacija>, 20 oglasa po stranici (?stranica=N); na vrhu su plaćeni oglasi, zatim po
zadnjoj izmjeni. Popis daje naslov, cijenu i početak opisa; mjesto ("Lokacija"), puni
opis, datum zadnje izmjene i tablica podataka su na stranici oglasa. Tablica (parse_features,
kad je oglašivač ispuni): vrsta kuće ili zemljišta, godina izgradnje i zadnje adaptacije,
stanje, kvadratura (kuće, okućnice), pristupni put i pravni status pristupa, priključci, broj
parkirnih mjesta, prateći objekti (garaža, bazen), čisto vlasništvo. Bez kvadrature: iz teksta.

Početno stanje (FULL): popisi naših mjesta (mjesto iz filtra) i prve dvije stranice
cijelog Kvarnera i Istre (oglasi izvan naših popisa se otvore). Redovno: te dvije
stranice; novi oglasi se otvaraju (najviše MAX_DETAILS po pokretanju, ostali sljedeći
put). "Cijena na upit" se preskače."""

import html
import re

from .. import prikljucci
from ..http import FetchError
from ..models import HOUSE, LAND, Listing
from ..text import area_matches, fmt_eur, fold, parse_number
from .base import DETAIL_RETRIES, FULL, Source, details_deadline, past

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
    nije stambena (prva takva je okućnica). Zemljište: najveća površina ("moguća gradnja
    kuće 150 m2 na zemljištu 800 m2")."""
    area = plot = None
    for pos, value in area_matches(text):
        if value < 20:
            continue
        if kind != HOUSE:
            area = max(area or 0, value)
            continue
        # Riječi ispred broja, samo iz istog dijela rečenice (ne preko prethodne površine).
        before = re.split(r"m2|m²|[,;!?]|\.\s", fold(text[max(0, pos - 40):pos]))[-1]
        if _NOT_LIVING.search(before):
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
        x.extra["povrsina_iz_teksta"] = True    # iz isječka: za poznat oglas vrijedi ona sa stranice oglasa
        _set_area(x)
        out.append(x)
    return out


def parse_features(page: str) -> dict[str, list[str]]:
    """Tablica podataka sa stranice oglasa: {naziv (fold): vrijednosti}. Redak naziv – vrijednost
    ("Vrsta kuće: Samostojeća kuća", "Godina izgradnje", "Kvadratura: 1334 m²") ili naslov s
    popisom ("Vrsta zemljišta", "Pristupni put", "Priključci", "Prateći objekti", "U blizini")."""
    table = re.search(r'class="bad-features"[^>]*>\s*<table[^>]*>(.*?)</table>', page, re.S)
    if not table:
        return {}
    out = {}
    for name, value in re.findall(r"<th[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>", table.group(1), re.S):
        value = _clean(re.sub(r"<sup>.*?</sup>", "", value))            # "m<sup>2</sup>" nije broj
        if value:
            out[fold(_clean(name))] = [value]
    for cell in re.findall(r"<td[^>]*>(.*?)</td>", table.group(1), re.S):
        name = re.search(r"<h6[^>]*>(.*?)</h6>", cell, re.S)
        values = [v for v in (_clean(li) for li in re.findall(r"<li[^>]*>(.*?)</li>", cell, re.S)) if v]
        if name and values:
            out[fold(_clean(name.group(1)))] = values
    return out


def _apply_features(x: Listing, features: dict[str, list[str]]) -> dict:
    """Podaci iz tablice u oglas; vraća površine iz polja ({"area", "plot"}) – postavljaju se
    nakon površina iz teksta (_set_area)."""
    def first(name: str) -> str:
        return (features.get(name) or [""])[0]

    def number(name: str) -> float | None:
        m = re.match(r"\s*(\d[\d.,]*)", first(name))      # "1334 m", "12.000 m", "477"
        return parse_number(m.group(1)) if m else None

    # "Vrsta zemljišta" je popis: "Građevinsko, Poljoprivredno" je mješovito (⚠), ne samo prva vrsta.
    kind = ", ".join(v for v in features.get("vrsta kuce" if x.kind == HOUSE else "vrsta zemljista") or [] if v)
    if kind:
        x.subtype = kind
    for name, key in (("godina izgradnje", "godina_izgradnje"), ("zadnja adaptacija", "godina_obnove")):
        year = re.fullmatch(r"(1[89]\d\d|20\d\d)\.?", first(name))
        if year:
            x.extra[key] = int(year.group(1))
    utilities = prikljucci.from_labels(features.get("prikljucci"))
    if utilities:
        x.extra["prikljucci"] = utilities
    access, legal = ", ".join(features.get("pristupni put") or []), first("pravni status pristupa")
    if access or legal:                                    # "Asfaltni put (pravo služnosti)"
        x.extra["pristup"] = f"{access} ({legal.lower()})" if access and legal else access or legal
    things = (features.get("prateci objekti") or []) + (features.get("opremljenost i sadrzaji") or [])
    parking = [v.lower() for v in things if re.search(r"garaz|parking|parkirn", fold(v))]
    spaces = number("broj parkirnih mjesta")
    if spaces:
        parking.append(f"parkirnih mjesta: {int(spaces)}")
    if parking:                                            # sam broj: "🚗 parkirnih mjesta: N"
        x.extra["parking"] = str(int(spaces)) if len(parking) == 1 and spaces else ", ".join(parking)
    if any(re.search(r"\bbazen", fold(v)) and not prikljucci.DENIED.search(fold(v)) for v in things):
        x.extra["bazen"] = True
    if any(fold(v) == "cisto vlasnistvo" for v in things):
        x.extra["vlasnicki_list"] = True
    if first("stanje nekretnine"):                          # "Starina" → za obnovu (filters)
        x.extra["stanje"] = first("stanje nekretnine").lower()
    if x.kind == HOUSE:
        return {"area": number("kvadratura kuce") or number("kvadratura"), "plot": number("kvadratura okucnice")}
    return {"area": number("kvadratura"), "plot": None}


def parse_detail(page: str, x: Listing) -> None:
    """Mjesto, puni opis, tablica podataka, površina (kvadratura, inače iz teksta), datum
    zadnje izmjene, oglašivač."""
    place = re.search(r'Lokacija:</h5>.*?class="place-name">([^<]+)<', page, re.S)
    if place:
        x.settlement = _clean(place.group(1))
        x.location_text = x.settlement
    desc = re.search(r'<div class="bad-text[^"]*"[^>]*>(.*?)</div>', page, re.S)
    if not place and not desc:
        raise ValueError("burza.com.hr: na stranici oglasa nema mjesta ni opisa")
    if desc:
        x.description = re.sub(r"^Opis:\s*", "", _clean(desc.group(1)))[:3000]
        x.extra.pop("opis_skracen", None)
    changed = re.search(r"Zadnja izmjena:\s*<strong>(\d{1,2})\.(\d{1,2})\.(\d{4})", page)
    if changed:
        x.published = f"{changed.group(3)}-{int(changed.group(2)):02d}-{int(changed.group(1)):02d}"
    advertiser = re.search(r"Podaci o oglašivaču\s*</[^>]+>\s*(?:<[^>]+>\s*)*([^<]{3,80})<", page)
    if advertiser:
        x.extra["oglasivac"] = _clean(advertiser.group(1))
    sizes = _apply_features(x, parse_features(page))
    _set_area(x)
    if sizes["area"] and sizes["area"] >= 20:
        x.area = sizes["area"]
    if sizes["plot"]:
        x.plot_area = sizes["plot"]
    x.extra.pop("povrsina_iz_teksta", None)


class Burza(Source):
    name = "burza"
    label = "burza.com.hr"
    baseline_report = False   # prvo pokretanje se samo zabilježi
    # 23. 10.: tablica podataka (vrsta kuće/zemljišta, priključci, pristupni put…) dosad se nije čitala;
    # polja2: i kvadratura kuće/okućnice, parking, adaptacija, stanje, pravni status pristupa.
    reopen_once = "polja2-2026-10"

    def _page(self, slug: str, location: str, page: int) -> str:
        return self.http.get(f"{BASE}/oglasi/{slug}/{location}" + (f"?stranica={page}" if page > 1 else "")).text

    def _list(self, slug: str, kind: str, location: str, place: str, pages) -> list[Listing]:
        out = []
        for page in pages:
            items = parse_list(self._page(slug, location, page), kind, place)
            if page == 1 and not items and location == REGION:   # cijela regija nikad nije prazna
                raise RuntimeError(f"burza.com.hr: popis {slug} je prazan (promjena stranice?)")
            out += [x for x in items if x.price]              # "cijena na upit" se preskače
            if len(items) < PAGE_SIZE:
                break
        return out

    def _detail(self, x: Listing) -> bool:
        try:
            parse_detail(self.http.get(x.url, retries=DETAIL_RETRIES).text, x)
            self.detail_result()
            return True
        except Exception as exc:  # noqa: BLE001
            x.extra["detalji_greska"] = str(exc)[:200]
            self.detail_result(f"{type(exc).__name__}: {exc}")
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
        self.add_pending(found, known_ids)
        out, details, deadline = [], 0, details_deadline()
        # Novi oglasi prvi. Poznat se otvara samo kod sniženja ili bez površine (reopen_known): poruka
        # o sniženju inače bi imala samo isječak opisa s popisa (npr. bez "dvojna kuća", 15. 10.).
        for x in sorted(found.values(), key=lambda x: x.source_id in known_ids):
            known = x.source_id in known_ids
            if known and not self.reopen_known(x):             # mjesto i površina iz ranijeg dohvata
                out.append(x)
            elif details < MAX_DETAILS and not past(deadline):
                details += 1
                if self._detail(x) or known or not self.defer(x, failed=True):
                    out.append(x)
            elif known or not self.defer(x):                   # sljedeći put (bez mjesta bi bili "nepoznata lokacija")
                out.append(x)                                  # čeka predugo (poznat ne čeka): podaci s popisa
        return out

    def reopen(self, row: dict) -> Listing | None:
        try:
            page = self.http.get(row["url"], retries=DETAIL_RETRIES).text
        except FetchError as exc:
            if str(exc).startswith(("HTTP 404", "HTTP 410")):
                return None
            raise
        x = Listing(source=self.name, source_id=row["source_id"], url=row["url"], title=row.get("title") or "",
                    kind=row["kind"], price=row.get("price"))
        x.extra["samo_pgz"] = True
        x.extra["opis_skracen"] = True
        parse_detail(page, x)
        return x

    def search_links(self):
        out = []
        for slug, kind in KINDS:
            price, _ = self.limits(kind)
            label = "kuće" if kind == HOUSE else "zemljišta"
            out.append((f"{label}, Kvarner i Istra, do {fmt_eur(price)} (površinu portal ne filtrira)",
                        f"{BASE}/oglasi/{slug}/{REGION}?pt={price}"))
        return out
