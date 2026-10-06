"""Banke i leasing kuće: prodaja preuzetih nekretnina (jednom dnevno).

Mjerenje 6. 10.: nijedna banka, leasing kuća ni agencija za naplatu nije imala kuću ili
zemljište na našem području. Prisilne prodaje idu kroz FINA e-dražbe (već pratimo), a
Addiko svoje nekretnine objavljuje na Njuškalu. Zato se stranice iz data/banke.yaml samo
prate: kad se pojavi novi tekst (rečenica ili stavka koje ranije nije bilo) koji spominje
naše mjesto, stiže kratka poruka s tim tekstom i poveznicom. Prvo čitanje stranice se
samo zabilježi."""

import hashlib
import html
import json
import re
from pathlib import Path

import yaml

from .text import fold

PAGES_FILE = Path(__file__).resolve().parent.parent / "data" / "banke.yaml"
# Nazivi naselja koji su i nazivi mjesta drugdje u Hrvatskoj (Županja, Ročko Polje, Draga kod Požege).
EXCLUDE = {"zupanje", "polje", "draga", "vrh"}
MAX_PER_PAGE = 3


def load_pages(path: Path = PAGES_FILE) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or []


def segments(page: str) -> list[str]:
    """Rečenice i stavke stranice (bez skripti, izbornika i podnožja)."""
    page = re.sub(r"(?is)<(script|style|nav|header|footer|noscript)[^>]*>.*?</\1>", " ", page or "")
    page = re.sub(r"(?i)<br\s*/?>|</(p|li|tr|td|div|h\d|a|option)>", "\n", page)
    text = html.unescape(re.sub(r"<[^>]+>", " ", page))
    out = []
    for line in text.splitlines():
        line = " ".join(line.split())
        for part in re.split(r"(?<=[.!?])\s+(?=[A-ZČĆŽŠĐ0-9])", line) if len(line) > 600 else [line]:
            if 15 <= len(part) <= 600:
                out.append(part)
    return list(dict.fromkeys(out))


def digest(segment: str) -> str:
    return hashlib.sha1(fold(segment).encode("utf-8")).hexdigest()[:12]


def our_places(locator, text: str) -> list[str]:
    """Naša mjesta spomenuta u tekstu (velikim početnim slovom, bez naziva koji postoje i drugdje)."""
    found = []
    for jls, name, written in locator._scan(text):      # (grad/općina, osnovni naziv, kako piše)
        if not jls.included or not written[:1].isupper() or name in locator.common_words or name in EXCLUDE:
            continue
        if jls.name not in found:
            found.append(jls.name)
    return found


def changes(locator, page: str, known: set[str]) -> tuple[list[tuple[str, list[str]]], set[str]]:
    """(novi odlomci koji spominju naše područje, svi sažeci stranice)."""
    current = segments(page)
    hashes = {digest(s) for s in current}
    new = [(s, our_places(locator, s)) for s in current if digest(s) not in known]
    return [(s, places) for s, places in new if places], hashes


def format_change(name: str, found: list[tuple[str, list[str]]]) -> str:
    e = html.escape
    lines = [f"🏦 <b>Prodaja nekretnina</b> · {e(name)}", "Novo na stranici, spominje naše područje:"]
    for text, places in found[:MAX_PER_PAGE]:
        lines.append(f"📍 {e(', '.join(places))}: „{e(text[:300])}”")
    if len(found) > MAX_PER_PAGE:
        lines.append(f"… i još {len(found) - MAX_PER_PAGE} – otvori stranicu")
    return "\n".join(lines)


def dumps(hashes: set[str]) -> str:
    return json.dumps(sorted(hashes))
