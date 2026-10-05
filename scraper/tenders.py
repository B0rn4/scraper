"""Natječaji za prodaju nekretnina: gradovi i općine, PGŽ, CERP, državne nekretnine.

Popis stranica i način čitanja je u data/natjecaji.yaml. Zadržavaju se samo objave o
prodaji nekretnina (zemljište, kuća, nekretnina, čestica); zakup, najam, vozila,
poslovni prostori, stanovi, zapošljavanje i rezultati natječaja se preskaču. Objave
regionalnih tijela (bez jls) moraju spominjati naše područje."""

import html
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
_SALE = re.compile(r"\b(prodaj\w*|kupoprodaj\w*|javn\w* nadmetanj\w*|licitacij\w*|draz\w*)")
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
        items = {"wp": self._wp, "rss": self._rss, "stranica": self._page}[method](site)
        if not site.get("jls"):        # regionalno tijelo: samo naše područje
            items = [t for t in items if self.area_of(f"{t.title}. {t.text}")]
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
                    found[x["link"]] = Tender(x["link"], site["naziv"], site.get("jls", ""), title, x["link"],
                                              (x.get("date") or "")[:10],
                                              _clean((x.get("content") or {}).get("rendered", ""))[:20000])
        return list(found.values())

    def _rss(self, site: dict) -> list[Tender]:
        out = []
        for word in ("prodaj",):
            xml = self.http.get(site["url"], params={"s": word, "feed": "rss2"}).text
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
                out.append(Tender(link, site["naziv"], site.get("jls", ""), title, link, published, _clean(body)[:20000]))
        return out

    def _page(self, site: dict) -> list[Tender]:
        page = self.http.get(site["url"])
        base = str(getattr(page, "url", site["url"]))
        out, seen = [], set()
        for href, inner in re.findall(r'<a[^>]+href="([^"#]+)"[^>]*>(.*?)</a>', page.text, re.S | re.I):
            title = _clean(inner)
            url = urljoin(base, html.unescape(href))
            if len(title) < 12 or url in seen or not relevant(title):
                continue
            seen.add(url)
            out.append(Tender(url, site["naziv"], site.get("jls", ""), title[:300], url))
        return out[:40]

    def load_text(self, tender: Tender) -> None:
        """Tekst objave za detalje (samo HTML; PDF i Word se ne čitaju)."""
        if tender.text or re.search(r"\.(pdf|docx?|xlsx?|zip)$", urlparse(tender.url).path, re.I):
            return
        try:
            body = self.http.get(tender.url).text
        except Exception:  # noqa: BLE001 – bez teksta objava ipak stiže
            return
        body = re.sub(r"(?is)<(script|style|nav|header|footer)[^>]*>.*?</\1>", " ", body)
        tender.text = _clean(body)[:20000]
        if not tender.published:
            dates = [d for _, d in dates_in(tender.text[:3000])]
            tender.extra["datum_iz_teksta"] = dates[0] if dates else ""
