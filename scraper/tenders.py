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
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import yaml

from .text import areas_in_text, fold, parse_number

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
_DEADLINE = re.compile(r"\b(rok\w*|najkasnije|zakljucno|ponude se (podnose|dostavljaju)|do dana)\b")
_TEASER = re.compile(r"\s+(?=(Na temelju|Temeljem|Sukladno|U skladu s)\b)")
_PDF = re.compile(r'<a[^>]+href="([^"]+\.pdf)"[^>]*>(.*?)</a>', re.I | re.S)
MIN_TEXT = 600            # kraći tekst objave: natječaj je vjerojatno u priloženom PDF-u
_PART = re.compile(r"\b\d+\s*/\s*\d+\s+(dijel|dio)\w*|\bsuvlasnick\w*\s+(dio|dijel|udio|udjel)\w*|\bidealn\w*\s+(dio|dijel)\w*")
_PRICE = re.compile(r"\b(pocetn\w*|najniz\w*|utvrden\w*)\s+(kupoprodajn\w*\s+)?cijen\w*[^0-9]{0,40}?(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?)\s*(eur|€)")


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


def _plain(text: str) -> str:
    """Mala slova bez dijakritika, interpunkcija ostaje (za datume i cijene)."""
    text = unicodedata.normalize("NFKD", (text or "").replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


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


def details(text: str) -> dict:
    """Rok za ponude, početna cijena, površine iz teksta natječaja."""
    plain = _plain(text)
    out = {}
    for m in _DEADLINE.finditer(plain):
        after = [d for pos, d in dates_in(text) if m.start() <= pos <= m.start() + 200]
        if after:
            out["rok"] = after[0]
            break
    prices = [parse_number(m.group(3)) for m in _PRICE.finditer(plain)]
    prices = [p for p in prices if p and p >= 1000]
    if prices:
        out["cijene"] = prices[:5]
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
            data = self.http.get(api, params={"search": word, "per_page": 30, "orderby": "date", "order": "desc",
                                              "_fields": "id,date,link,title,content"}).json()
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


def format_tender(t: Tender, info: dict, parcel_lines: list[str]) -> str:
    """Telegram HTML poruka za natječaj."""
    e = html.escape
    lines = [f"📜 <b>Natječaj za prodaju</b> · {e(t.site)}", f"<b>{e(t.title[:250])}</b>"]
    when = []
    published = t.published or t.extra.get("datum_iz_teksta", "")
    if published:
        when.append(f"📅 objavljeno {fmt_date(published)}")
    if info.get("rok"):
        when.append(f"⏳ rok {fmt_date(info['rok'])}")
    if when:
        lines.append(" · ".join(when))
    money = []
    if info.get("cijene"):
        prices = ", ".join(f"{p:,.0f} €".replace(",", ".") for p in info["cijene"][:3])
        money.append(f"početna cijena {prices}")
    if info.get("povrsine"):
        money.append(", ".join(f"{a:,.0f} m²".replace(",", ".") for a in info["povrsine"][:3]))
    if money:
        lines.append("💶 " + e(" · ".join(money)))
    if t.jls and t.jls not in t.site:
        lines.append(f"📍 {e(t.jls)}")
    lines += [e(x) for x in parcel_lines[:3]]
    if info.get("dio"):
        lines.append("⚠ prodaje se dio nekretnine (suvlasnički udio) – provjeri")
    if len(t.text) < 200:
        lines.append("<i>Detalji su u priloženom dokumentu – otvori objavu.</i>")
    elif t.extra.get("iz_pdf"):
        lines.append("<i>Podaci iz priloženog PDF-a.</i>")
    return "\n".join(lines)[:3800]
