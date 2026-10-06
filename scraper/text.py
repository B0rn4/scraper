"""Pomoćne funkcije za tekst: normalizacija i čitanje brojeva."""

import re
import unicodedata

_FOLD = str.maketrans({"đ": "d", "Đ": "D"})
_SAINT = re.compile(r"\b(?:sv|sveti|sveta|sveto|svetog|svetoga|svetom|svetoj|svete|svetu)\b\.?", re.I)


def fold_case(text: str) -> str:
    """Kao fold(), ali čuva velika slova. fold(x) == fold_case(x).lower(),
    pa pozicije u oba teksta odgovaraju jedna drugoj."""
    text = (text or "").translate(_FOLD)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[\-–—/_,;:()\"'„“”]+", " ", text)
    text = _SAINT.sub(lambda m: "Sv" if m.group(0)[0].isupper() else "sv", text)
    text = re.sub(r"(?<=\w)\.(?=\s|$)", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def fold(text: str) -> str:
    """Mala slova, bez dijakritika, crtice i interpunkcija kao razmaci.

    "Kostrena-Lucija" i "Kostrena Lucija" daju isto; "Sveti", "Sv." → "sv".
    """
    return fold_case(text).lower()


def parse_number(text) -> float | None:
    """Čita broj u hrvatskom ili engleskom zapisu: "1.234,56", "1,234.56", "309.31", "1.200"."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    s = re.sub(r"[^\d.,]", "", str(text))
    if not s or not re.search(r"\d", s):
        return None
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        # "1,200" je tisuću dvjesto (engleski zapis), ali "0,345" je decimalni broj.
        s = s.replace(",", "") if len(tail) == 3 and head and head != "0" else s.replace(",", ".")
    elif s.count(".") == 1:
        head, _, tail = s.partition(".")
        if len(tail) == 3 and head and head != "0":
            s = head + tail  # "1.200" je tisuću dvjesto, ne 1,2
    else:
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


SQ_FATHOM_M2 = 3.596652  # 1 čhv (četvorni hvat)

_AREA = re.compile(
    r"(\d{1,3}(?:\.\d{3})+(?:,\d+)?|(?<![\d.,])\d{1,3}(?:[ \u00a0]\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)"
    r"\s*(m2|m²|m\s?2|čhv|čh|chv|ha|hektar\w*)(?!\w)",
    re.I,
)


def areas_in_text(text: str) -> list[float]:
    """Sve površine iz slobodnog teksta, preračunate u m²."""
    return [value for _, value in area_matches(text)]


def area_matches(text: str) -> list[tuple[int, float]]:
    """Površine s položajem u tekstu: [(položaj broja, m²)]."""
    found = []
    for m in _AREA.finditer(text or ""):
        value = parse_number(m.group(1))
        if value is None:
            continue
        unit = m.group(2).lower()
        if unit.startswith("č") or unit.startswith("ch"):
            value *= SQ_FATHOM_M2
        elif unit.startswith("ha") or unit.startswith("hektar"):
            value *= 10_000
        found.append((m.start(), round(value, 1)))
    return found


def fmt_eur(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:,.0f} €".replace(",", ".")


def fmt_m2(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:,.0f} m²".replace(",", ".")
