"""Natječaji za prodaju nekretnina: gradovi i općine, PGŽ, CERP, državne nekretnine.

Popis stranica i način čitanja je u data/natjecaji.yaml. Zadržavaju se samo objave o
prodaji nekretnina (zemljište, kuća, nekretnina, čestica); zakup, najam, vozila,
poslovni prostori, stanovi, zapošljavanje i rezultati natječaja se preskaču. Objave
regionalnih tijela (bez jls) moraju spominjati naše područje."""

import html
import io
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from urllib.parse import urljoin, urlparse

import yaml

from .ispu import _KO, parcel_mentions
from .text import area_matches, areas_in_text, fmt_eur, fmt_m2, fold, parse_number

SITES_FILE = Path(__file__).resolve().parent.parent / "data" / "natjecaji.yaml"

# Nad fold() tekstom (mala slova, bez dijakritika; "/" je razmak).
_SALE = re.compile(r"\b(prodaj\w*|kupoprodaj\w*|javn\w* nadmetanj\w*|licitacij\w*|draz\w*|ponud\w* za kupnj\w*)")
_OBJECT = re.compile(r"\b(nekretnin\w*|zemlj?ist\w*|zemjist\w*|gradevinsk\w*|kuc[aeiu]\w*|kuca\b|cestic\w*|k\.? ?c\.?\s*(br\.?\s*)?\d|parcel\w*|starin\w*)")
_LAND_OR_HOUSE = re.compile(r"\b(zemlj?ist\w*|zemjist\w*|gradevinsk\w*|kuc[aeiu]\w*|kuca\b|cestic\w*|parcel\w*|k\.? ?c\.?\s*(br\.?\s*)?\d)")
_EXCLUDE = re.compile(r"\b(zakup\w*|najam\w*|najm\w*|vozil\w*|automobil\w*|cistilic\w*|umjetnin\w*|mljekomat\w*|oprem\w*"
                      r"|plovil\w*|brod\w*|poslovn\w* prostor\w*|stan(a|ova|ove)?\b|garaz\w*|udjel\w*|dionic\w*)")
# Nije sam natječaj: savjetovanje, odluka o odabiru, rezultati, poništenje.
_NOT_TENDER = re.compile(r"\b(savjetovanj\w*|odabir\w*|izbor\w* najpovoljnij\w*|najpovoljnij\w*|ponistenj\w*|ponisten\w*"
                         r"|rezultat\w*|zapisnik\w*|obustav\w*)")
_DATE = re.compile(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(20\d\d)|(\d{1,2})\.\s*(sijecnja|veljace|ozujka|travnja|svibnja|lipnja|srpnja"
                   r"|kolovoza|rujna|listopada|studenoga|studenog|prosinca)\s*(20\d\d)")
_MONTHS = {"sijecnja": 1, "veljace": 2, "ozujka": 3, "travnja": 4, "svibnja": 5, "lipnja": 6, "srpnja": 7, "kolovoza": 8,
           "rujna": 9, "listopada": 10, "studenoga": 11, "studenog": 11, "prosinca": 12}
# Rok za ponude: prvo izričiti izrazi, pa bilo koji "rok". "U roku od 15 dana od dana objave … dana
# 29. ožujka" je datum objave + 15 dana, osim kad tekst navodi i izričit datum ("zaključno s 20.7.").
_DEADLINE_STRONG = re.compile(r"\b(rok\w* za (podnosenje|dostavu|predaju|primitak|zaprimanje) (pisanih )?ponud\w*"
                              r"|ponud\w* (se )?(podnose|dostavljaju|predaju|zaprimaju)|krajnji rok|zakljucno (s|sa|do)\b"
                              r"|najkasnije do)")
_DEADLINE = re.compile(r"\b(rok\w*|najkasnije|zakljucno|ponude se (podnose|dostavljaju)|do dana)\b")
_NOT_DEADLINE = re.compile(r"rok\w* (vazenja|zakljucenja|placanja|isplate|za (sklapanje|zakljucenje|placanje|isplatu|uplatu))")
_NDAYS = re.compile(r"\b(\d{1,2})\s*(\(\w+\)\s*)?dan\w*[,\s]+(od|nakon|racunajuci|po)\b")
_EXPLICIT = re.compile(r"(zakljucno|najkasnije|\bdo)\s*(s|sa|do)?\s*(dana\s*)?$")
_TEASER = re.compile(r"\s+(?=(Na temelju|Temeljem|Sukladno|U skladu s)\b)")
_PDF = re.compile(r'<a[^>]+href="([^"]+\.pdf)"[^>]*>(.*?)</a>', re.I | re.S)
MIN_TEXT = 600            # kraći tekst objave: natječaj je vjerojatno u priloženom PDF-u
_PART = re.compile(r"\b\d+\s*/\s*\d+\s+(dijel|dio)\w*|\bsuvlasnick\w*\s+(dio|dijel|udio|udjel)\w*|\bidealn\w*\s+(dio|dijel)\w*")
_NUM = r"(\d{1,3}(?:[. ]\d{3})+(?:,\d+)?|\d+(?:,\d+)?)"
_PER_M2 = r"(\w*\s*(?:/|po)\s*(?:m\s?2|metr\w* kvadratn\w*|kvadratn\w* metr\w*))?"
# "početna cijena … 65.000,00 EUR", "početna cijena za k.č. 12/3 iznosi 65.000 €", "… 120,00 EUR/m2"
# "početna (natječajna) cijena … iznosu od ukupno 4.300,00 €" (do iznosa ne smije biti drugi iznos ni jamčevina)
_PRICES = (re.compile(r"\b(pocetn\w*|najniz\w*|utvrden\w*)\s+(\w+\s+)?cijen\w*[^0-9]{0,40}?" + _NUM
                      + r"\s*(eur|€)" + _PER_M2),
           re.compile(r"\b(pocetn\w*|najniz\w*|utvrden\w*)\s+(\w+\s+)?cijen\w*(?:(?!eur|€|jamcevin)[\s\S]){0,400}?"
                      r"\biznos\w*\s+(?:od\s+)?(?:ukupno\s+)?" + _NUM + r"\s*(eur|€)" + _PER_M2))
# Prodaja više čestica kao jedne cjeline (jedna početna cijena za sve).
_AS_WHOLE = re.compile(r"\b(kao (jedn\w* )?cjelin\w*|u cjelini|zajedno kao|jedinstven\w* (cjelin|nekretnin)\w*)")
# Natječaj samo za stanove/poslovne prostore/garaže (npr. Državne nekretnine): bez zemljišta i kuća.
_FLAT = re.compile(r"\b(stan\b|stana\b|stanovi\b|stanova\b|\(stan \d|stambeni prostor|poslovn\w* prostor\w*|garaz\w*)")
_LAND_WORDS = re.compile(r"\b(zemljiste|zemljista|zemljistu|zemljistem|kuc[aeiu]\b|kuca\b|kucom\b|okucnic\w*|oranic\w*"
                         r"|pasnjak\w*|livad\w*|vocnjak\w*|vinograd\w*|sum[aeu]\b|dvorist\w*|neplodno|ruin\w*|rusevin\w*"
                         r"|stambena zgrada|gospodarsk\w* zgrad\w*|gradiliste)")
_HOUSE = re.compile(r"\b(kuc[aeiu]\w*|kuca\b|stamben\w* (zgrad|objekt)\w*)")


@dataclass
class Tender:
    key: str                  # adresa objave
    site: str                 # naziv tijela
    jls: str                  # grad/općina (prazno za regionalna tijela)
    title: str
    url: str
    published: str = ""       # ISO datum ili prazno (nepoznato)
    text: str = ""            # tekst objave (za detalje)
    extra: dict = field(default_factory=dict)


@dataclass
class Lot:
    """Čestica (ili skupina čestica pod jednim brojem natječaja) s početnom cijenom i
    površinom kad ih tekst navodi uz nju. Podatke iz ISPU-a i usporedbe dodaje runner."""
    ko: str
    kcs: list[str]
    price: float | None = None           # početna cijena, €
    ppm: float | None = None             # početna cijena po m² (kad je natječaj tako navodi)
    area: float | None = None            # površina iz teksta natječaja
    house: bool = False                  # uz česticu se spominje kuća
    land_registry: bool = False          # z.k.č. (zemljišnoknjižna oznaka): katastar se ne provjerava
    parts: int = 1                       # više čestica prodanih kao cjelina
    context: str = ""                    # tekst oko spomena čestice (za prepoznavanje naselja)
    cadastre_area: float | None = None   # površina iz katastra (samo za jednu česticu)
    gp: str = ""                         # građevinsko područje (ISPU) ili "nije pronađena u katastru"
    ppv_range: str = ""                  # PPV na lokaciji kad nema cijene za usporedbu
    notes: list[str] = field(default_factory=list)   # usporedbe cijene (PPV, medijan)

    @property
    def label(self) -> str:
        return f"{'z.k.č.' if self.land_registry else 'k.č.'} {', '.join(self.kcs)} k.o. {self.ko}"

    @property
    def size(self) -> float | None:
        """Površina za €/m²: iz teksta (može se prodavati dio čestice), inače iz katastra."""
        return self.area or self.cadastre_area

    @property
    def unit_price(self) -> float | None:
        if self.ppm:
            return self.ppm
        if self.price and self.size:
            return self.price / self.size
        return None


@lru_cache(maxsize=4096)
def _plain_char(c: str) -> str:
    if c in "đĐ":
        return "d"
    base = "".join(x for x in unicodedata.normalize("NFKD", c) if not unicodedata.combining(x))
    return (base[:1] or c).lower()[:1] or c


def _plain(text: str) -> str:
    """Mala slova bez dijakritika, interpunkcija ostaje (za datume i cijene). Duljina
    teksta ostaje ista, pa se položaji poklapaju s izvornim tekstom."""
    return "".join(_plain_char(c) for c in (text or ""))


def _prices(plain: str) -> list[tuple[int, float, bool]]:
    """Početne cijene: [(položaj broja, iznos, je li po m²)]."""
    found = {}
    for regex in _PRICES:
        for m in regex.finditer(plain):
            value = parse_number(m.group(3).replace(" ", ""))
            per = bool(m.group(5))
            if value and (1 <= value <= 5000 if per else value >= 100):
                found.setdefault(m.start(3), (m.start(3), value, per))
    return sorted(found.values())


def lots(text: str, limit: int = 20) -> list[Lot]:
    """Čestice iz teksta natječaja, s cijenom i površinom koje stoje uz njih.

    Vrijednost se veže uz prethodni spomen čestice ("k.č. 12/3 … površine 650 m²,
    početna cijena 65.000 €"), a kad tekst navodi vrijednosti prije čestica (prva
    vrijednost je prije prvog spomena), uz sljedeći. Čestica s više različitih
    vrijednosti ostaje bez njih (nejasno), pa poruka pokazuje samo popis cijena."""
    text = unicodedata.normalize("NFC", text or "")
    mentions = parcel_mentions(text)
    if not mentions:
        return []
    plain = _plain(text)
    starts = [m.start for m in mentions]
    keys = [(fold(m.ko), tuple(m.kcs)) for m in mentions]
    order = list(dict.fromkeys(keys))
    by_key = {}
    for m, k in zip(mentions, keys):
        if k not in by_key:
            by_key[k] = Lot(m.ko, list(m.kcs), land_registry=m.land_registry)

    def owners(values: list[tuple]) -> dict[tuple, list[tuple]]:
        out: dict[tuple, list[tuple]] = {}
        if len(order) == 1:
            return {order[0]: list(values)}
        forward = bool(values) and values[0][0] < starts[0]
        for v in values:
            if forward:
                i = next((i for i, s in enumerate(starts) if s >= v[0]), None)
            else:
                i = max((i for i, s in enumerate(starts) if s <= v[0]), default=None)
            if i is not None:
                out.setdefault(keys[i], []).append(v)
        return out

    all_prices = _prices(plain)
    prices = owners(all_prices)
    areas = owners([(pos, a) for pos, a in area_matches(text) if a >= 10])
    for i, m in enumerate(mentions):
        lot = by_key[keys[i]]
        stop = starts[i + 1] if i + 1 < len(starts) else m.start + 500
        if _HOUSE.search(plain[max(0, m.start - 150):min(stop, m.start + 500)]):
            lot.house = True
        if not lot.context:
            lot.context = text[max(0, m.start - 120):m.end + 120]
    for key, lot in by_key.items():
        totals = {v for _, v, per in prices.get(key, []) if not per}
        per_m2 = {v for _, v, per in prices.get(key, []) if per}
        sizes = {a for _, a in areas.get(key, [])}
        lot.price = totals.pop() if len(totals) == 1 else None
        lot.ppm = per_m2.pop() if len(per_m2) == 1 else None
        lot.area = sizes.pop() if len(sizes) == 1 else None
    found = [by_key[k] for k in order]
    totals = {v for _, v, per in all_prices if not per}
    if len(found) > 1 and len(totals) == 1 and _AS_WHOLE.search(plain):
        # "k.č. 159/3 … 154 m2, k.č. 172/4 … 47 m2 … prodaju se kao cjelina. Početna cijena: 101.141,63"
        sizes = [x.area for x in found]
        whole = Lot(found[0].ko, [kc for x in found for kc in x.kcs], price=totals.pop(),
                    area=sum(sizes) if all(sizes) else None, house=any(x.house for x in found),
                    context=" ".join(x.context for x in found), land_registry=found[0].land_registry)
        whole.parts = len(found)
        found = [whole]
    return found[:limit]


def flats_only(text: str) -> bool:
    """Natječaj samo za stanove, poslovne prostore ili garaže (bez zemljišta i kuća)."""
    plain = _plain(text)
    return bool(_FLAT.search(plain)) and not _LAND_WORDS.search(plain)


def fails_criteria(found: list[Lot], criteria: dict) -> str:
    """Razlog kad sve čestice natječaja sigurno promašuju kriterije (premale ili preskupe),
    inače "". Nepoznata površina ili cijena → ne promašuje (poruka stiže)."""
    if not found:
        return ""
    reasons = []
    for lot in found:
        limits = criteria.get("kuca" if lot.house else "zemljiste", {})
        total = lot.price or (lot.ppm * lot.size if lot.ppm and lot.size else None)
        if not lot.house and lot.size and lot.size < limits.get("min_povrsina", 0):
            reasons.append(f"{lot.label}: {fmt_m2(lot.size)}")
        elif total and total > limits.get("max_cijena", float("inf")):
            reasons.append(f"{lot.label}: {fmt_eur(total)}")
        else:
            return ""
    return "; ".join(reasons)


def place_text(t: "Tender", found: list[Lot], cadastral: bool = True) -> str:
    """Tekst za prepoznavanje naselja: naslov i okolina spomena čestica (ne cijeli tekst –
    zaglavlje navodi sjedište općine). cadastral=False izostavlja nazive katastarskih
    općina: k.o. može obuhvaćati više naselja (k.o. Jušići i mjesto Matulji)."""
    if cadastral:
        return ". ".join([t.title, *(f"{lot.context} {lot.ko}" for lot in found)])
    return ". ".join([_KO.sub(" ", t.title), *(_KO.sub(" ", lot.context) for lot in found)])


def load_sites(path: Path = SITES_FILE) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or []


def _clean(value: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value or "")).split())


def relevant(title: str) -> bool:
    """Objava o prodaji nekretnine (po naslovu)."""
    t = fold(title)
    if not _SALE.search(t) or not _OBJECT.search(t) or _NOT_TENDER.search(t):
        return False
    return not (_EXCLUDE.search(t) and not _LAND_OR_HOUSE.search(t))


def _date(day, month, year) -> str:
    try:
        return datetime(int(year), int(month), int(day)).date().isoformat()
    except ValueError:
        return ""


def dates_in(text: str) -> list[tuple[int, str]]:
    out = []
    for m in _DATE.finditer(_plain(text)):
        if m.group(1):
            out.append((m.start(), _date(m.group(1), m.group(2), m.group(3))))
        else:
            out.append((m.start(), _date(m.group(4), _MONTHS[m.group(5)], m.group(6))))
    return [(pos, d) for pos, d in out if d]


def _deadline(text: str, plain: str) -> tuple[str, bool] | None:
    """(datum, je li približan) roka za ponude."""
    dates = dates_in(text)
    for regex in (_DEADLINE_STRONG, _DEADLINE):
        for m in regex.finditer(plain):
            if _NOT_DEADLINE.match(plain, m.start()):
                continue
            after = [(pos, d) for pos, d in dates if m.start() <= pos <= m.start() + 250]
            if not after:
                continue
            explicit = [d for pos, d in after if _EXPLICIT.search(plain[max(0, pos - 30):pos])]
            if explicit:
                return explicit[0], False
            days = _NDAYS.search(plain, m.start(), min(len(plain), m.start() + 120))
            if days:
                return (date.fromisoformat(after[0][1]) + timedelta(days=int(days.group(1)))).isoformat(), True
            return after[0][1], False
    return None


def details(text: str) -> dict:
    """Rok za ponude, početna cijena, površine iz teksta natječaja."""
    plain = _plain(text)
    out = {}
    deadline = _deadline(text, plain)
    if deadline:
        out["rok"], approximate = deadline
        if approximate:
            out["rok_priblizno"] = True
    found = _prices(plain)
    prices = list(dict.fromkeys(v for _, v, per in found if not per))
    per_m2 = list(dict.fromkeys(v for _, v, per in found if per))
    if prices:
        out["cijene"] = prices[:5]
    if per_m2:
        out["cijene_m2"] = per_m2[:5]
    if _PART.search(plain):
        out["dio"] = True
    areas = [a for a in areas_in_text(text) if a >= 50]
    if areas:
        out["povrsine"] = areas[:5]
    return out


class Reader:
    def __init__(self, http, locator):
        self.http = http
        self.locator = locator

    def fetch(self, site: dict) -> list[Tender]:
        method = site.get("nacin")
        items = {"wp": self._wp, "rss": self._rss, "feed": self._rss, "stranica": self._page}[method](site)
        if not site.get("jls"):        # regionalno tijelo: samo naše područje (iz naslova i teksta)
            for t in items[:15]:
                self.load_text(t)
            items = [t for t in items[:15] if self.area_of(f"{t.title}. {t.text}")]
            for t in items:
                t.jls = self.area_of(f"{t.title}. {t.text}")
        return items

    def area_of(self, text: str) -> str:
        names = [j.name for j, _ in self.locator.scan_text(text) if j.included]
        return names[0] if names else ""

    def _wp(self, site: dict) -> list[Tender]:
        api = urljoin(site["url"], "wp-json/wp/v2/posts")
        found: dict[str, Tender] = {}
        for word in ("prodaj", "nadmetanj"):
            resp = self.http.get(api, params={"search": word, "per_page": 30, "orderby": "date", "order": "desc",
                                              "_fields": "id,date,link,title,content"})
            try:
                data = resp.json()
            except ValueError:
                raise RuntimeError(f"wp-json nije vratio JSON: {' '.join(resp.text[:150].split())}") from None
            for x in data if isinstance(data, list) else []:
                title = _clean((x.get("title") or {}).get("rendered", ""))
                if relevant(title) and x.get("link") not in found:
                    raw = (x.get("content") or {}).get("rendered", "")
                    found[x["link"]] = Tender(x["link"], site["naziv"], site.get("jls", ""), title, x["link"],
                                              (x.get("date") or "")[:10], _clean(raw)[:20000], {"html": raw[:200000]})
        return list(found.values())

    def _rss(self, site: dict) -> list[Tender]:
        out = []
        for word in ("prodaj",):
            params = {"s": word, "feed": "rss2"} if site.get("nacin") == "rss" else None
            xml = self.http.get(site["url"], params=params).text
            for block in re.findall(r"<item>(.*?)</item>", xml, re.S):
                def tag(name, b=block):
                    m = re.search(rf"<{name}>(.*?)</{name}>", b, re.S)
                    return re.sub(r"<!\[CDATA\[|\]\]>", "", m.group(1)).strip() if m else ""
                title, link = _clean(tag("title")), tag("link")
                if not relevant(title):
                    continue
                try:
                    published = datetime.strptime(tag("pubDate")[:16], "%a, %d %b %Y").date().isoformat()
                except ValueError:
                    published = ""
                body = tag("content:encoded") or tag("description")
                out.append(Tender(link, site["naziv"], site.get("jls", ""), title, link, published, _clean(body)[:20000],
                                  {"html": html.unescape(body)[:200000]}))
        return out

    def _page(self, site: dict) -> list[Tender]:
        page = self.http.get(site["url"])
        base = str(getattr(page, "url", site["url"]))
        out, seen = [], set()
        for href, inner in re.findall(r"""<a[^>]+href=["']([^"'#]+)["'][^>]*>(.*?)</a>""", page.text, re.S | re.I):
            full = _clean(inner)
            if re.search(r"\bneaktivn", fold(full)):    # Omišalj: istekli natječaji su "Neaktivno"
                continue
            title = _TEASER.split(full, 1)[0].split(" | ")[0].strip()   # "Natječaj … Na temelju članka 48. …"
            url = urljoin(base, html.unescape(href))
            if len(title) < 12 or url in seen or not relevant(title):
                continue
            seen.add(url)
            out.append(Tender(url, site["naziv"], site.get("jls", ""), title[:300], url))
        return out[:40]

    def load_text(self, tender: Tender) -> None:
        """Tekst objave za detalje. Kad je objava kratka, a ima priložen PDF (ili je
        sama objava PDF), čita se i PDF (prvih nekoliko stranica)."""
        path = urlparse(tender.url).path
        if re.search(r"\.pdf$", path, re.I):
            tender.text = tender.text or self.pdf_text(tender.url)
            tender.extra["iz_pdf"] = bool(tender.text)
        elif not tender.text and not re.search(r"\.(docx?|xlsx?|zip)$", path, re.I):
            try:
                body = self.http.get(tender.url).text
            except Exception:  # noqa: BLE001 – bez teksta objava ipak stiže
                body = ""
            tender.extra["html"] = body[:300000]
            body = re.sub(r"(?is)<(script|style|nav|header|footer)[^>]*>.*?</\1>", " ", body)
            tender.text = _clean(body)[:20000]
        if len(tender.text) < MIN_TEXT and tender.extra.get("html"):
            pdfs = _PDF.findall(tender.extra["html"])
            pdfs.sort(key=lambda p: not re.search(r"natje|prodaj|oglas", fold(f"{p[0]} {p[1]}")))
            if pdfs:
                text = self.pdf_text(urljoin(tender.url, html.unescape(pdfs[0][0])))
                if text:
                    tender.text = f"{tender.text}\n{text}"[:30000]
                    tender.extra["iz_pdf"] = True
        tender.extra.pop("html", None)
        if not tender.published:
            dates = [d for _, d in dates_in(tender.text[:3000])]
            tender.extra["datum_iz_teksta"] = dates[0] if dates else ""

    def pdf_text(self, url: str, pages: int = 8) -> str:
        try:
            from pypdf import PdfReader
            data = self.http.get(url).content
            if len(data) > 15_000_000:
                return ""
            reader = PdfReader(io.BytesIO(data))
            return " ".join(" ".join((p.extract_text() or "").split()) for p in reader.pages[:pages])[:30000]
        except Exception:  # noqa: BLE001 – PDF nije nužan za obavijest
            return ""

def fmt_date(iso: str) -> str:
    try:
        d = datetime.fromisoformat(iso[:10]).date()
    except ValueError:
        return iso
    return f"{d.day}. {d.month}. {d.year}."


def _lot_lines(lot: Lot) -> list[str]:
    e = html.escape
    area = ""
    if lot.size:
        area = f" ({fmt_m2(lot.size)}"
        if lot.area and lot.cadastre_area and abs(lot.area / lot.cadastre_area - 1) > 0.1:
            area += f"; cijela čestica u katastru {fmt_m2(lot.cadastre_area)}"
        area += ")"
    gp = f": {lot.gp}" if lot.gp else ""
    ppv = f" · {lot.ppv_range}" if lot.ppv_range and not lot.unit_price else ""
    whole = " – prodaju se zajedno" if lot.parts > 1 else ""
    lines = [e(f"🗺 {lot.label}{whole}{area}{gp}{ppv}")]
    if lot.house and (lot.price or lot.ppm):
        lines.append(e(f"💶 početna cijena {fmt_eur(lot.price) if lot.price else fmt_eur(lot.ppm) + '/m²'} (s kućom)"))
    elif lot.ppm:
        total = f" (≈ {fmt_eur(lot.ppm * lot.size)})" if lot.size else ""
        lines.append(e(f"💶 početna cijena {fmt_eur(lot.ppm)}/m²{total}"))
    elif lot.price:
        unit = f" · {fmt_eur(lot.unit_price)}/m²" if lot.unit_price else ""
        lines.append(e(f"💶 početna cijena {fmt_eur(lot.price)}{unit}"))
    return lines + [e(x) for x in lot.notes]


def format_tender(t: Tender, info: dict, found: list[Lot] | None = None, summary: str = "", place: str = "",
                  warnings: list[str] | None = None, max_lots: int = 3) -> str:
    """Telegram HTML poruka za natječaj (obična poruka, do 4096 znakova): sažetak, rok,
    mjesto, za svaku česticu građevinsko područje, početna cijena i €/m² s usporedbama
    (PPV, medijan traženih), pa upozorenja. Kad je preduga, izostavljaju se čestice s kraja."""
    e = html.escape
    found = found or []
    head = [f"📜 <b>Natječaj za prodaju</b> · {e(t.site)}", f"<b>{e(t.title[:250])}</b>"]
    if summary:
        head.append(e(summary))
    when = []
    published = t.published or t.extra.get("datum_iz_teksta", "")
    if published:
        when.append(f"📅 objavljeno {fmt_date(published)}")
    if info.get("rok"):
        when.append(f"⏳ rok {'≈ ' if info.get('rok_priblizno') else ''}{fmt_date(info['rok'])}")
    if when:
        head.append(" · ".join(when))
    place = place or (t.jls if t.jls and t.jls not in t.site else "")
    if place:
        head.append(f"📍 {e(place)}")
    shown = [lot for lot in found if lot.gp or lot.price or lot.ppm or lot.area][:max_lots]
    body = [_lot_lines(lot) for lot in shown]
    tail = []
    if len(found) > len(shown) and shown:
        tail.append(f"… i još {len(found) - len(shown)} čestica – vidi objavu")
    if not any(lot.price or lot.ppm for lot in shown):
        money = []
        if info.get("cijene"):
            money.append("početna cijena " + ", ".join(fmt_eur(p) for p in info["cijene"][:3]))
        if info.get("cijene_m2"):
            money.append("početna cijena " + ", ".join(f"{fmt_eur(p)}/m²" for p in info["cijene_m2"][:3]))
        if info.get("povrsine"):
            money.append(", ".join(fmt_m2(a) for a in info["povrsine"][:3]))
        if money:
            tail.append(e("💶 " + " · ".join(money)))
    tail += [e(f"⚠ {w}") for w in (warnings if warnings is not None else
                                     (["prodaje se dio nekretnine (suvlasnički udio) – provjeri"] if info.get("dio") else []))]
    if len(t.text) < 200:
        tail.append("<i>Detalji su u priloženom dokumentu – otvori objavu.</i>")
    elif t.extra.get("iz_pdf"):
        tail.append("<i>Podaci iz priloženog PDF-a.</i>")
    while body and len("\n".join(head + [x for b in body for x in b] + tail)) > 3800:
        body.pop()
    return "\n".join(head + [x for b in body for x in b] + tail)[:4000]
