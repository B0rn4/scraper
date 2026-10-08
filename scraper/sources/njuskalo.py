"""Njuškalo – čita se s Redmija (kućna IP adresa), pravim preglednikom.

Njuškalo štiti ShieldSquare: zahtjevi bez preglednika nakon nekoliko pokušaja dobiju
captchu, a Chromium s trajnim profilom prolazi (proba 5. 10. 2026.).

Popis je poredan po datumu objave (sort=new), ali na vrhu su većinom stari oglasi
koje agencije ponovno objave – zadržavaju stari broj oglasa. Brojevi oglasa rastu
(~20.000 dnevno na cijelom Njuškalu), pa je oglas nov ako mu je broj veći od
najvećeg dosad viđenog umanjenog za OLD_MARGIN. Stariji oglas koji vidimo prvi put
zabilježi se bez obavijesti (extra["stari_oglas"]); sniženje cijene i dalje stiže.

Popis ne daje površinu zemljišta, a vrstu kuće samo ugrubo, pa se za nove oglase
na našem području otvara i stranica oglasa (površine, vrsta, opis, koordinate)."""

import gzip
import html
import re
import statistics
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..browser import Browser
from ..models import HOUSE, LAND, Listing
from ..text import areas_in_text, fmt_eur, fmt_m2, parse_number
from .base import FULL, Source, details_deadline, past

BASE = "https://www.njuskalo.hr"
REGION = "primorsko-goranska"
CATEGORIES = [("prodaja-kuca", HOUSE), ("prodaja-zemljista", LAND)]
MAX_PAGES = 4          # najviše stranica po kategoriji u jednom pokretanju
CATCHUP_PAGES = 10     # kad prošlo čitanje nije stiglo do oglasa od pretprošlog (jutro nakon noći, ispad)
MAX_DETAILS = 8        # najviše otvorenih oglasa u jednom pokretanju (zaštita od captche)
OLD_MARGIN = 60_000    # ~3 dana novih brojeva oglasa
CAPTCHA_PAUSE = timedelta(hours=2)   # nakon captche na stranici oglasa (REDMI.md: zaštitu ostaviti na miru)
# Popis bez oglasa (promjena stranice ili zaštita koja ne piše "captcha"): stranica se sprema
# ovdje, a šalje s "python tools/redmi_probe.py --posalji" (grana debug) da se vidi što je to.
FAILED_PAGES = Path(__file__).resolve().parents[2] / "redmi-out"

# Redovni i plaćeno istaknuti (VauVau, SuperVau); "Latest" su najnoviji oglasi cijelog Njuškala.
_ITEM = re.compile(r'<li class="EntityList-item EntityList-item--n\d+ EntityList-item--(Regular|VauVau|SuperVau)[^"]*">(.*?)</article>',
                   re.S)
_LINK = re.compile(r'<h3 class="entity-title"><a href="([^"]+)"[^>]*name="(\d+)"[^>]*>.*?<span>([^<]*)</span>', re.S)
_DESC = re.compile(r'<div class="entity-description">(.*?)</div>', re.S)
_DATE = re.compile(r'<time[^>]*datetime="([^"]+)"')
_PRICE = re.compile(r'<strong class="price[^"]*">([^<]+)</strong>')
_IMG = re.compile(r'<img[^>]+src="(https://[^"]+)"')
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_TAGS = re.compile(r"<[^>]+>")


def _text(fragment: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", _TAGS.sub(" ", _COMMENT.sub("", fragment)))).strip()


def _place(value: str) -> tuple[str, str]:
    """"Krk, Linardići" → ("Krk", "Linardići"); detalj ima i županiju ispred."""
    parts = [p.strip() for p in value.split(",") if p.strip()]
    if parts and parts[0].lower().startswith("primorsko-goransk"):
        parts = parts[1:]
    return (parts[0] if parts else "", parts[1] if len(parts) > 1 else "")


def parse_list(page: str, kind: str) -> list[Listing]:
    out = []
    for m in _ITEM.finditer(page):
        block = m.group(2)
        link = _LINK.search(block)
        if not link:
            continue
        href, sid, title = link.groups()
        desc = _DESC.search(block)
        lines = [_text(x) for x in re.split(r"<br\s*/?>", desc.group(1))] if desc else []
        lines = [x for x in lines if x]
        fields = {}
        subtype = ""
        for line in lines:
            if ":" in line:
                key, value = line.split(":", 1)
                fields[key.strip().lower()] = value.strip()
            elif not subtype:
                subtype = line
        municipality, settlement = _place(fields.get("lokacija", ""))
        title = html.unescape(title).strip()
        area = parse_number((re.search(r"[\d.,]+", fields.get("stambena površina", "")) or [None])[0])
        from_title = kind == LAND and not area
        if from_title:
            found = areas_in_text(title)
            area = max(found) if found else None
        price = _PRICE.search(block)
        date = _DATE.search(block)
        img = _IMG.search(block)
        out.append(Listing(
            source=Njuskalo.name,
            source_id=sid,
            url=BASE + href,
            title=title,
            kind=kind,
            subtype=subtype,
            price=parse_number(price.group(1).replace("€", "")) if price else None,
            area=area,
            county="Primorsko-goranska",
            municipality=municipality,
            settlement=settlement,
            location_text=fields.get("lokacija", ""),
            image_url=img.group(1) if img else "",
            published=date.group(1) if date else "",
            extra={"istaknut": m.group(1) != "Regular", "samo_popis": True,   # opis tek sa stranice oglasa
                   "povrsina_iz_teksta": from_title},
        ))
    return out


def parse_detail(page: str, listing: Listing) -> None:
    """Dopunjuje oglas podacima sa stranice oglasa."""
    page = _COMMENT.sub("", page)
    fields = {}
    for dt, dd in re.findall(r'<dt class="ClassifiedDetailBasicDetails-listTerm">(.*?)</dt>\s*'
                             r'<dd class="ClassifiedDetailBasicDetails-listDefinition">(.*?)</dd>', page, re.S):
        fields[_text(dt).lower()] = _text(dd)

    def number(key):
        value = fields.get(key)
        return parse_number(re.search(r"[\d.,]+", value).group(0)) if value and re.search(r"\d", value) else None

    if listing.kind == HOUSE:
        if fields.get("tip kuće"):
            listing.subtype = f"{fields['tip kuće']} kuća"
        listing.area = number("stambena površina") or listing.area
        listing.plot_area = number("površina okućnice") or listing.plot_area
    else:
        if fields.get("tip zemljišta"):
            listing.subtype = f"{fields['tip zemljišta'].capitalize()} zemljište"
        listing.area = number("površina") or listing.area
    if fields.get("lokacija"):
        listing.municipality, listing.settlement = _place(fields["lokacija"])
        listing.location_text = fields["lokacija"]
    desc = re.search(r'<div class="ClassifiedDetailDescription-text"[^>]*>(.*?)</div>', page, re.S)
    groups = [_text(x) for x in re.findall(r'<li class="ClassifiedDetailPropertyGroups-groupListItem">(.*?)</li>', page, re.S)]
    text = _text(re.sub(r"<br\s*/?>", "\n", desc.group(1))) if desc else ""
    listing.description = "\n".join(filter(None, [text, "; ".join(groups)]))[:5000]
    coords = re.search(r'"coordinates":\{"latitude":([-\d.]+),"longitude":([-\d.]+)\},"isApproximateLocationOnMap":(\w+)', page)
    if coords:
        listing.extra["lat"], listing.extra["lon"] = float(coords.group(1)), float(coords.group(2))
        listing.extra["priblizna_lokacija"] = coords.group(3) == "true"
    for key, name in (("broj parkirnih mjesta", "parking"), ("godina izgradnje", "godina_izgradnje"),
                      ("namjena", "namjena")):
        if fields.get(key):
            listing.extra[name] = fields[key]
    if "ClassifiedDetailUnavailableNotice" in page and not listing.extra.get("neaktivan"):
        # "Ovaj oglas je neaktivan.": stiže s upozorenjem – oglašivač je i dalje dostupan, a
        # drugi oglas više ne vide (do njega se dolazi samo izravnom poveznicom).
        listing.extra["neaktivan"] = True
        listing.extra.setdefault("warnings", []).append("oglas je istekao (Njuškalo: neaktivan, nije više na popisu)")
    listing.extra["detalji"] = True
    listing.extra.pop("samo_popis", None)
    listing.extra.pop("povrsina_iz_teksta", None)


def _is_captcha(page: str) -> bool:
    return "captcha" in (re.search(r"<title>([^<]*)", page) or [None, ""])[1].lower()


def _describe(page: str) -> str:
    """Naslov i veličina stranice, za poruku o grešci ("promjena stranice?" ili zaštita)."""
    title = " ".join((re.search(r"<title[^>]*>([^<]*)", page) or [None, ""])[1].split())[:80]
    return f"naslov stranice: „{title or 'bez naslova'}”, {len(page) // 1024} kB"


def _save_failed(category: str, page: str) -> None:
    """Sprema stranicu popisa bez oglasa (najviše zadnje 4) za slanje Claudeu."""
    try:
        FAILED_PAGES.mkdir(exist_ok=True)
        path = FAILED_PAGES / f"{time.strftime('%m%d-%H%M')}_njuskalo_greska_{category}.html.gz"
        path.write_bytes(gzip.compress(page.encode("utf-8", "replace")))
        for old in sorted(FAILED_PAGES.glob("*_njuskalo_greska_*.html.gz"))[:-4]:
            old.unlink()
    except OSError:
        pass


def _page_url(category: str, page: int) -> str:
    return f"{BASE}/{category}/{REGION}?sort=new" + (f"&page={page}" if page > 1 else "")


def _old_threshold(known_ids: set[str], found: dict[str, Listing]) -> float | None:
    """Brojevi oglasa do ovog su "stari" (ponovno objavljeni). Polazi od medijana 50 najvećih
    poznatih brojeva, ne od najvećeg, i bez brojeva većih od svih na trenutnim stranicama:
    jedan neobičan broj (druga numeracija, pogrešno pročitan) inače bi sve nove oglase
    proglasio starima."""
    newest = max((int(k) for k in found if k.isdigit()), default=None)
    top = sorted((int(k) for k in known_ids if k.isdigit() and (newest is None or int(k) <= newest + OLD_MARGIN)),
                 reverse=True)[:50]
    return statistics.median(top) - OLD_MARGIN if top else None


class Njuskalo(Source):
    name = "njuskalo"
    label = "Njuškalo"
    baseline_report = False   # početni popis bi bio samo prva stranica – ne šalje se

    def __init__(self, *args, browser: Browser | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.browser = browser

    def fetch(self, mode, known_ids):
        browser = self.browser or Browser()
        own_browser = self.browser is None
        since = self.since_time()
        found: dict[str, Listing] = {}
        self.incomplete, self.reached, self.deep_error = False, "", ""
        pages = 1 if mode == FULL else (CATCHUP_PAGES if self.catch_up else MAX_PAGES)

        def stopped(oldest: str) -> None:
            """Čitanje kategorije stalo prije oglasa od prošlog pokretanja."""
            if since and mode != FULL:
                self.incomplete = True
                self.reached = max(self.reached, oldest)

        try:
            for category, kind in CATEGORIES:
                oldest = ""
                for page in range(1, pages + 1):
                    deep = page > MAX_PAGES
                    if deep and self.deep_error:      # zaštita se već javila dublje: ne čita se dalje
                        stopped(oldest)
                        break
                    try:
                        text = browser.get(_page_url(category, page), "li.EntityList-item")
                        if _is_captcha(text):
                            raise RuntimeError("Njuškalo je vratio captchu (zaštita ShieldSquare)")
                    except Exception as exc:  # noqa: BLE001
                        if not deep:
                            raise
                        # Sustizanje je dodatak: captcha ili greška dublje ne ruši čitanje (pročitano
                        # ostaje), a nepročitano javlja runner.
                        self.deep_error = f"stranica {page}: {exc}"[:200]
                        stopped(oldest)
                        break
                    items = parse_list(text, kind)
                    if not items:
                        if page == 1:
                            _save_failed(category, text)
                            raise RuntimeError(f"Njuškalo: na stranici {category} nema oglasa ({_describe(text)}) – "
                                               "promjena stranice ili zaštita?")
                        # Popis tolikog područja ne završava nakon nekoliko stranica: stranica se
                        # nije učitala, a oglasi iza nje nisu pročitani.
                        stopped(oldest)
                        break
                    for x in items:
                        found.setdefault(x.source_id, x)
                    # Sljedeća stranica samo ako je i najstariji redovni oglas objavljen nakon
                    # prošlog pokretanja (inače smo sve novo već vidjeli).
                    dates = [x.published for x in items if not x.extra.get("istaknut") and x.published]
                    oldest = min(dates) if dates else oldest
                    if not since or not dates or datetime.fromisoformat(oldest.replace("Z", "+00:00")) < since:
                        break
                else:                   # najviše stranica, a oglasi od prošlog pokretanja nisu dosegnuti
                    stopped(oldest)
            if mode != FULL:
                self.add_pending(found, known_ids)
            threshold = _old_threshold(known_ids, found)
            # Nakon captche na stranici oglasa ne otvara se nijedna CAPTCHA_PAUSE (zaštita bi
            # inače ostala na oprezu); kraj stanke pamti runner (captcha_until). Stanka dalja od
            # CAPTCHA_PAUSE (sat na mobitelu bio je naprijed) ne vrijedi.
            now = datetime.now(timezone.utc)
            until = self.captcha_until or ""
            self.detail_blocked = now.isoformat(timespec="seconds") < until <= (
                now + CAPTCHA_PAUSE).isoformat(timespec="seconds")
            self.detail_ok = False
            details, later, deadline = 0, set(), details_deadline()
            for x in found.values():
                if x.source_id in known_ids:
                    continue
                if threshold is not None and int(x.source_id) <= threshold:
                    x.extra["stari_oglas"] = True
                elif mode != FULL and not x.extra.get("detalji") and self.worth_detail(x):
                    # Sljedeći put (bez stranice oglasa stigao bi bez površine); čeka li predugo
                    # (MAX_DEFERRALS), stiže s podacima s popisa.
                    if details >= MAX_DETAILS or self.detail_blocked or past(deadline):
                        if self.defer(x):
                            later.add(x.source_id)
                        continue
                    details += 1
                    try:
                        page = browser.get(x.url, "h1")
                        if _is_captcha(page):     # nije greška oglasa: ne broji se kao pokušaj
                            self.detail_blocked = True
                            self.captcha_until = (now + CAPTCHA_PAUSE).isoformat(timespec="seconds")
                            x.extra["detalji_greska"] = "stranica oglasa: captcha"
                            if self.defer(x):
                                later.add(x.source_id)
                            continue
                        if "ClassifiedDetail" not in page:
                            raise RuntimeError("stranica oglasa bez podataka")
                        parse_detail(page, x)
                        self.detail_result()
                    except Exception as exc:  # noqa: BLE001 – pokušava se ponovno sljedeći put
                        x.extra["detalji_greska"] = str(exc)[:200]
                        self.detail_result(f"{type(exc).__name__}: {exc}")
                        if self.defer(x, failed=True):
                            later.add(x.source_id)
        finally:
            if own_browser:
                browser.close()
        # Odgođeni oglasi se pamte (runner) i otvaraju sljedeći put, i kad su pali s pročitanih stranica.
        return [x for x in found.values() if x.source_id not in later]


    def search_links(self):
        out = []
        for cat, kind in CATEGORIES:
            price, area = self.limits(kind)
            extra = f"&livingArea%5Bmin%5D={area}" if kind == HOUSE else ""   # površinu zemljišta postavi na stranici
            label = (f"kuće, PGŽ, najnovije, do {fmt_eur(price)}, od {fmt_m2(area)}" if kind == HOUSE
                     else f"zemljišta, PGŽ, najnovije, do {fmt_eur(price)}")
            out.append((label, _page_url(cat, 1) + f"&price%5Bmax%5D={price}" + extra))
        return out
