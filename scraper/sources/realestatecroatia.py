"""realestatecroatia.com (Labin d.o.o., sustav Agentor kojim mnoge agencije vode oglase).

Faza 5 (agencije): stranice agencija su većinom iza Cloudflareove zaštite, a ovaj portal
radi iz oblaka i ima oglase većine agencija s našeg područja. Mjerenje 6. 10.: od
oglasa koji prolaze kriterije oko 95 % već imamo s naših portala; ostatak (~4 %) su
oglasi koje agencija drži samo ovdje.

Popis cijele PGŽ: list.asp?regija=8&vrsta=1 (kuće) / 3 (zemljišta)&akcija=1 (prodaja),
sort=objekt_id&smjer=desc (najnoviji prvi; broj oglasa raste i ne mijenja se pri
osvježavanju), cijenaDo=granica iz kriterija. Cijena je zapisana "530,000 €". Mjesto
je "ČIŽIĆI (KRK)" – u zagradi otok ili općina. Površina je samo na stranici oglasa,
pa se otvaraju novi oglasi koji bi mogli proći (najviše MAX_DETAILS po pokretanju; ostali
čekaju sljedeće pokretanje, da ne stignu bez površine).
"Cijena na upit" se preskače (gotovo uvijek luksuzne vile iznad granice)."""

import html
import re
import time

from ..models import HOUSE, LAND, Listing
from ..text import fmt_eur, parse_number
from .base import DETAIL_RETRIES, FULL, Source, details_deadline, past

BASE = "https://www.realestatecroatia.com/hrv/"
REGION_PGZ = 8
KINDS = [(1, HOUSE, "kuca"), (3, LAND, "zemljiste")]
PAGE_SIZE = 20
MAX_DETAILS = 10
DEEP_SECONDS = 240     # dnevno dublje čitanje: najviše toliko po vrsti (kuće, zemljišta)


def _clean(value: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value or "")).split())


def parse_list(page: str, kind: str) -> list[Listing]:
    out = []
    for attrs, block in re.findall(r"<li([^>]*)>(.*?)</li>", page, re.S):
        rid = re.search(r"detail\.asp\?id=(\d+)", block)
        if not rid:
            continue
        price = re.search(r'class="cijena">\s*([\d.,]+)\s*&#8364;', block)
        place = re.search(r"Mjesto:\s*(?:<br\s*/?>\s*)*<strong>(.*?)</strong>", block, re.S)
        vrsta = re.search(r"Vrsta:\s*<strong>([^<]+)</strong>", block)
        title = re.search(r'<strong><a href="detail\.asp\?id=\d+"[^>]*>(.*?)</a>', block, re.S)
        agency = re.search(r'showconn\.asp\?id=\d+"><strong>([^<]+)', block)
        snippet = re.search(r"</a></strong>\s*<br\s*/?>(.*?)</td>", block, re.S)
        image = re.search(r'<img src="(https://data\.realestatecroatia\.com/[^"]+)"', block)
        where = _clean(place.group(1)) if place else ""
        x = Listing(
            source=RealEstateCroatia.name,
            source_id=rid.group(1),
            url=f"{BASE}detail.asp?id={rid.group(1)}",
            title=_clean(title.group(1)) if title else "",
            kind=kind,
            subtype=_clean(vrsta.group(1)).capitalize() if vrsta else "",
            price=float(re.sub(r"[.,]", "", price.group(1))) if price else None,
            settlement=re.sub(r"\s*\(.*\)\s*$", "", where).title(),
            location_text=where.title(),
            description=_clean(snippet.group(1)) if snippet else "",
            image_url=image.group(1) if image else "",
        )
        x.extra["agencija"] = _clean(agency.group(1)) if agency else ""
        x.extra["istaknut"] = "FFFFCC" in attrs.upper()      # plaćeni oglas na vrhu, izvan redoslijeda
        x.extra["opis_skracen"] = True
        out.append(x)
    return out


def parse_detail(page: str, x: Listing) -> None:
    """Površina, okućnica, puni opis i slika sa stranice oglasa."""
    text = _clean(re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", page))
    area = re.search(r"Površina:\s*([\d.,]+)\s*m2", text)
    plot = re.search(r"Okućnica:\s*([\d.,]+)\s*m2", text)
    desc = re.search(r"OPIS OBJEKTA\s*Hrvatski English Deutsch Italiano Ruski\s*(.*?)(?:Interni broj|REC ID)", text)
    image = re.search(r'(https://data\.realestatecroatia\.com/thumbnails/userimages/[^"\']+\.jpe?g)', page, re.I)
    if not area and not desc:
        # Ni površine ni opisa: stranica se promijenila (ili nije učitana), ne "oglas bez podataka".
        raise ValueError("realestatecroatia.com: na stranici oglasa nema površine ni opisa")
    if area:
        x.area = parse_number(area.group(1))
    if plot and x.kind == HOUSE:
        x.plot_area = parse_number(plot.group(1))
    if desc:
        x.description = desc.group(1)[:3000]
        x.extra.pop("opis_skracen", None)
    if image:
        x.image_url = image.group(1)


class RealEstateCroatia(Source):
    name = "realestatecroatia"
    label = "realestatecroatia.com"
    baseline_report = False   # prvo pokretanje se samo zabilježi (oglasi agencija su većinom već poslani)

    def _list(self, vrsta: int, cap: float, page: int) -> str:
        return self.http.get(f"{BASE}list.asp?regija={REGION_PGZ}&vrsta={vrsta}&akcija=1&sort=objekt_id&smjer=desc"
                             f"&cijenaDo={int(cap)}&page={page}").text

    deep_daily = True   # popis je po broju oglasa: sniženje ispod granice vidi se samo dubljim čitanjem

    def fetch(self, mode, known_ids):
        found: dict[str, Listing] = {}
        # Jednom dnevno (deep) cijeli popis do granice cijene, najviše DEEP_SECONDS: oglas koji
        # je bio skuplji od granice pa pojeftinio pojavi se duboko, na mjestu svog broja.
        deep = mode != FULL and self.deep
        self.deep_error = ""
        for vrsta, kind, key in KINDS:
            cap = self.criteria[key]["max_cijena"]
            deadline = time.monotonic() + DEEP_SECONDS
            regular_done = False             # redovno čitanje bi ovdje stalo (dalje je samo dublje)
            for page in range(1, (250 if mode == FULL or deep else 10) + 1):   # redovno: staje kod poznatih
                if deep and page > 1 and time.monotonic() > deadline:
                    break
                try:
                    items = parse_list(self._list(vrsta, cap, page), kind)
                except Exception as exc:  # noqa: BLE001
                    if not regular_done:
                        raise
                    # Greška na dubljoj stranici ne ruši redovno čitanje (novi oglasi s vrha ostaju).
                    self.deep_error = f"{key}, stranica {page}: {type(exc).__name__}: {exc}"[:200]
                    break
                if page == 1 and not items:      # kuća i zemljišta u PGŽ-u uvijek ima
                    raise RuntimeError(f"realestatecroatia.com: popis {key} je prazan (promjena stranice?)")
                for x in items:
                    if x.price:                      # "cijena na upit" se preskače
                        found.setdefault(x.source_id, x)
                # Najnoviji prvi: kad je i najstariji redovni oglas na stranici poznat, dalje su
                # samo stariji. (Ne "bilo koji poznat": oglasi odgođeni prošli put su između.)
                regular = [x for x in items if not x.extra["istaknut"] and x.price]
                regular_done = regular_done or bool(
                    regular and min(regular, key=lambda x: int(x.source_id)).source_id in known_ids)
                if len(items) < PAGE_SIZE or (mode != FULL and not deep and regular_done):
                    break
        if mode == FULL:
            return list(found.values())
        self.add_pending(found, known_ids)
        out, details, deadline = [], 0, details_deadline()
        for x in sorted(found.values(), key=lambda x: (not x.extra.get("odgodjen"), -int(x.source_id))):
            if x.source_id in known_ids or not self.worth_detail(x):
                out.append(x)
                continue
            if details >= MAX_DETAILS or past(deadline):
                if not self.defer(x):  # otvara se sljedeći put (bez površine bi stigao kao ⚠)
                    out.append(x)      # čeka predugo: stiže s podacima s popisa
                continue
            details += 1
            try:
                parse_detail(self.http.get(x.url, retries=DETAIL_RETRIES).text, x)
                self.detail_result()
            except Exception as exc:  # noqa: BLE001 – pokušava se ponovno sljedeći put
                x.extra["detalji_greska"] = str(exc)[:200]
                self.detail_result(f"{type(exc).__name__}: {exc}")
                if self.defer(x, failed=True):
                    continue
            out.append(x)
        return out

    def search_links(self):
        out = []
        for vrsta, kind, label in ((1, HOUSE, "kuće"), (3, LAND, "zemljišta")):
            price, _ = self.limits(kind)
            out.append((f"{label}, PGŽ, najnovije, do {fmt_eur(price)} (površinu portal ne filtrira)",
                        f"{BASE}list.asp?regija={REGION_PGZ}&vrsta={vrsta}&akcija=1&sort=objekt_id&smjer=desc&cijenaDo={price}"))
        return out
