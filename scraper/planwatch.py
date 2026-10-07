"""Nove odluke o prostornim planovima naših gradova i općina, za tjedni izvještaj.

Uvjeti gradnje (data/uvjeti_gradnje.yaml) prepisani su iz planova ručno, a planovi se
mijenjaju kad grad ili općina donese izmjenu – bilo kada u godini. Zato se jednom tjedno
provjerava:
- Službene novine PGŽ-a (sn.pgz.hr): popis odluka svakog grada/općine za tekuću i prošlu
  godinu; uzimaju se odluke čiji naslov spominje prostorni ili urbanistički plan;
- Registar prostornih planova Zavoda za prostorno uređenje PGŽ-a (zavod.pgz.hr): ondje su
  i odluke gradova i općina s vlastitim službenim glasilom (Crikvenica, Kostrena,
  Kraljevica, Lovran…).
Pamte se adrese već viđenih odluka; prvo čitanje samo zabilježi stanje."""

import json
import re
from dataclasses import dataclass
from datetime import datetime
from html import unescape
from urllib.parse import urljoin

from .text import fold

SN = "https://www.sn.pgz.hr/"
# Šifre gradova i općina na sn.pgz.hr.
SN_PLACES = {"Omišalj": "51513", "Krk": "51500", "Punat": "51521", "Baška": "10007", "Malinska-Dubašnica": "51511",
             "Vrbnik": "51516", "Dobrinj": "51514", "Opatija": "10006", "Matulji": "51211", "Lovran": "51415",
             "Rijeka": "51000", "Kostrena": "51221", "Kraljevica": "10001", "Crikvenica": "10003"}
REGISTRY = "https://zavod.pgz.hr/planovi_i_izvjesca/registar-prostornih-planova"
PLAN = re.compile(r"plan\w* uređenja|prostorn\w* plan\w*|urbanističk\w* plan|generaln\w* urbanistič|\b(UPU|PPUO?G?|GUP)\b", re.I)
# Odluke o odborima, financiranju i sl. spominju plan, ali ga ne mijenjaju.
NOT_PLAN = re.compile(r"odbor|povjerenstv|ugovor|financiran|sufinancir|program\w* (mjera|rada)|proračun", re.I)
LINK = re.compile(r"<a\b[^>]*?href=[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", re.I | re.S)
SEEN_KEY = "planovi:vidjeno"
SOURCES_KEY = "planovi:izvori"     # izvori pročitani barem jednom: prvo čitanje izvora samo bilježi
MAX_SEEN = 5000


@dataclass
class PlanDecision:
    jls: str
    title: str
    url: str


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def sn_page_urls(year: int) -> list[tuple[str, str]]:
    """(grad/općina, adresa popisa) za tekuću i prošlu godinu."""
    return [(name, f"{SN}default.asp?Link=popis&sifra={code}&godina={y}")
            for name, code in SN_PLACES.items() for y in (year, year - 1)]


def sn_decisions(html: str, jls: str, base: str = SN) -> list[PlanDecision]:
    out = []
    for href, label in LINK.findall(html or ""):
        link = urljoin(base, unescape(href.strip()))
        title = _text(label)
        if "Link=odluke" in link and "id=" in link and PLAN.search(title) and not NOT_PLAN.search(title):
            out.append(PlanDecision(jls, title[:300], link))
    return out


def registry_decisions(html: str, base: str = REGISTRY) -> list[PlanDecision]:
    """Odluke iz Zavodova registra (sn_jls/<grad>/<godina>_<broj>_<id>_<vrsta>.pdf) za naše
    gradove i općine: naziv plana i broj glasila iz retka tablice u kojem je poveznica."""
    ours = {fold(name).replace("-", " "): name for name in SN_PLACES}
    out = []
    for m in LINK.finditer(html or ""):
        link = urljoin(base, unescape(m.group(1).strip()))
        folder = re.search(r"/sn_jls/([^/]+)/([^/]+)$", link, re.I)
        if not folder:
            continue
        jls = ours.get(fold(folder.group(1)).replace("_", " ").replace("-", " "))
        if not jls:
            continue
        start = html.rfind("<tr", 0, m.start())
        end = html.find("</tr>", m.end())
        row = html[start:end] if start != -1 and end != -1 and end - start < 8000 else ""
        name = re.search(r'class="namePlan"[^>]*>(.*?)</div>', row, re.S)
        gazette = _text(m.group(2))
        if name:                          # registar: naziv plana i broj glasila u retku tablice
            title = f"{_text(name.group(1))} (glasilo {gazette})"
        else:
            kind = re.search(r"_izrada\d*\.pdf$", folder.group(2), re.I)
            title = ("odluka o izradi – " if kind else "") + (_text(row) or gazette)
        out.append(PlanDecision(jls, title[:300], link))
    return out


@dataclass
class Result:
    new: list[PlanDecision]
    known: int                        # koliko je odluka zapamćeno (s ovim čitanjem)
    errors: list[str]
    _updates: dict

    def save(self, state) -> None:
        """Zapamti pročitano – tek kad je izvještaj poslan, da se nove odluke ne izgube."""
        for key, value in self._updates.items():
            state.meta_set(key, value)


def check(get, state, year: int | None = None) -> Result:
    """Nove odluke od prošlog spremljenog čitanja. get(url) vraća HTML ili baca grešku.
    Prvo uspješno čitanje nekog izvora (grad na sn.pgz.hr, registar) samo bilježi njegove
    odluke – inače bi prvi izvještaj nabrojao sve odluke od 2003. naovamo."""
    year = year or datetime.now().year
    by_source: dict[str, list[PlanDecision]] = {}
    errors: list[str] = []
    for jls, url in sn_page_urls(year):
        try:
            by_source.setdefault(f"sn:{jls}", []).extend(sn_decisions(get(url), jls, url))
        except Exception as exc:  # noqa: BLE001 – jedan grad ne smije srušiti provjeru
            errors.append(f"Službene novine PGŽ, {jls}: {type(exc).__name__}")
    try:
        by_source["registar"] = registry_decisions(get(REGISTRY))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Registar Zavoda: {type(exc).__name__}")
    seen = json.loads(state.meta_get(SEEN_KEY) or "[]")
    sources = set(json.loads(state.meta_get(SOURCES_KEY) or "[]"))
    known = set(seen)
    new, added = [], []
    for source, items in by_source.items():
        for d in items:
            if d.url in known:
                continue
            known.add(d.url)
            added.append(d.url)
            if source in sources:
                new.append(d)
    updates = {}
    if added:
        updates[SEEN_KEY] = json.dumps((seen + added)[-MAX_SEEN:], ensure_ascii=False)
    if set(by_source) - sources:
        updates[SOURCES_KEY] = json.dumps(sorted(sources | set(by_source)), ensure_ascii=False)
    return Result(new, len(known), errors, updates)
