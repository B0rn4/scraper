"""Priključci zemljišta (struja, voda, kanalizacija…): redak 🔌 u poruci (odluka korisnika 13. 10.).

Iz polja oglasa kad ih portal ima (index.hr, vender, nekretnine.hr, Njuškalo, burza; oglasnik i
realestatecroatia ih za zemljišta nemaju). Inače rečenica iz opisa koja ih spominje – kao citat,
jer opis zna reći i "nema struje" ili "voda na 50 m od parcele". Kad ih ni pun opis ne spominje:
"nisu navedeni". Portal navodi samo ono što postoji: priključak koji nije naveden nije "nema"
(index.hr npr. nema polje za struju)."""

import re

from .models import LAND, Listing
from .risks import sentences
from .text import fold

# Redoslijed u poruci i uzorci za nazive polja s portala (bilo koji jezik; tekst nakon fold()).
KINDS = [
    ("struja", re.compile(r"struj|elektr|elettric")),
    ("voda", re.compile(r"\bvod(a|e|u|om)\b|vodovod|vodoopskrb|\bacqua\b")),
    ("kanalizacija", re.compile(r"kanaliz|odvodnj|\bfogn")),
    ("septička jama", re.compile(r"septi")),
    ("plin", re.compile(r"\bplin|\bgas\b")),
    ("asfaltni put", re.compile(r"asfalt")),
    ("javna rasvjeta", re.compile(r"rasvjet|illuminazione")),
    ("internet", re.compile(r"internet|\boptick")),          # burza: "Priključci: … Internet"
]
_NOT_UTILITY = re.compile(r"grijanj|bojler|klima")              # "električno grijanje" nije priključak
# Nijekanje u nazivu polja (nakon fold(), bez dvotočke): "Struja: Ne" → "struja ne", "bez struje".
DENIED = re.compile(r"\bne$|\b(nema|bez|nije)\b")
# Rečenice opisa: prvo one o priključcima općenito, zatim o pojedinom, na kraju o asfaltu.
_GENERAL = re.compile(r"prikljuc|infrastruktur|komunaln\w* (oprem|prikljuc|infrastr)")
_SPECIFIC = re.compile(r"\bstruj\w*|elektricn\w* (energ|prikljuc|mrez)|\bvod(a|e|u|om)\b|vodovod\w*|kanalizacij\w*"
                       r"|odvodnj\w*|\bplin(a|om|u|ovod\w*)?\b")
_ROAD = re.compile(r"asfalt\w*")
# "Pogled na more i vodu", "uz more i vodu" nisu priključak vode, "priključak na brzu cestu" nije
# priključak (čvor ceste).
_VIEW = re.compile(r"pogled\w*[^.,;]{0,25}|\bmor\w*\s+i\s+vod\w*|\bvod\w*\s+i\s+mor\w*|\bmor\w*"
                   r"|prikljuc\w* (na )?(brz\w* cest\w*|autocest\w*|autoput\w*|obilaznic\w*)"
                   r"|(drustven|prometn|turistick|sportsk|javn)\w* infrastruktur\w*")   # bolnice, ceste… nisu priključci
_PARTS = re.compile(r"(\s*[,;•*]\s*|\s+[–—-]\s+)")
MAX_QUOTE = 140


def from_labels(labels) -> list[str]:
    """Priključci iz naziva polja ili oznaka portala ("Priključak za vodu", "Struja",
    "allaccio elettricità", "Gradska kanalizacija"), redom kao u KINDS."""
    found = set()
    for label in labels or []:
        folded = fold(str(label))
        if DENIED.search(folded) or _NOT_UTILITY.search(folded):
            continue
        found |= {name for name, rx in KINDS if rx.search(folded)}
    return [name for name, _ in KINDS if name in found]


def merge(*groups) -> list[str]:
    found = {name for group in groups for name in group or []}
    return [name for name, _ in KINDS if name in found]


def quote(text: str) -> tuple[str, str]:
    """(o čemu je, rečenica iz opisa do 140 znakova): o priključcima ili, kad njih nema, o
    asfaltiranom pristupu; ("", "") kad opis ne spominje ni jedno."""
    candidates = sentences(text)
    for what, pattern in (("priključci", _GENERAL), ("priključci", _SPECIFIC), ("pristup", _ROAD)):
        for sentence in candidates:
            if pattern.search(_mentions(sentence)):
                return what, _excerpt(sentence, pattern)
    return "", ""


def _mentions(text: str) -> str:
    return _VIEW.sub(" ", fold(text))


def _excerpt(sentence: str, pattern) -> str:
    """Duga rečenica (nabrajanje "1/1, uredno, …, struja, voda 50 m, …"): dio sa spomenom i
    nastavak, s izvornom interpunkcijom, do MAX_QUOTE znakova."""
    if len(sentence) <= MAX_QUOTE:
        return sentence
    pieces = _PARTS.split(sentence)
    parts, seps = pieces[0::2], pieces[1::2]
    start = next((i for i, part in enumerate(parts) if part and pattern.search(_mentions(part))), 0)
    text, end = parts[start], start
    while end + 1 < len(parts) and len(text) + len(seps[end]) + len(parts[end + 1]) <= MAX_QUOTE - 2:
        text += seps[end] + parts[end + 1]
        end += 1
    if len(text) > MAX_QUOTE - 2:
        text, end = text[:MAX_QUOTE - 3].rstrip(), -1          # i sam dio je predug
    return ("…" if start else "") + text.strip() + ("" if end == len(parts) - 1 else "…")


def check(listing: Listing) -> str:
    """Redak 🔌 za zemljište ("" za kuću ili kad se ništa ne zna)."""
    if listing.kind != LAND:
        return ""
    names = listing.extra.get("prikljucci") or []
    access = listing.extra.get("pristup") or ""          # nekretnine.hr: "Na makadamskoj cesti"
    what, found = ("", "") if names else quote(f"{listing.title}. {listing.description or ''}")
    if names:
        line = "🔌 priključci: " + " · ".join(f"{name} ✔" for name in names)
    elif what == "priključci":
        line = f"🔌 priključci (iz opisa): „{found}”"
    elif found:
        line = f"🔌 priključci nisu navedeni · pristup (iz opisa): „{found}”"
    elif listing.description and not (listing.extra.get("opis_skracen") or listing.extra.get("samo_popis")):
        line = "🔌 priključci nisu navedeni"
    else:
        line = "🔌 priključci: nema podataka" if access else ""
    return f"{line} · pristup: {access[:1].lower()}{access[1:]}" if access else line
