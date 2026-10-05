"""Parking uz kuću: treba parkirno mjesto (garaža, mjesto u dvorištu…) ili dovoljno
okućnice da se auto može parkirati.

Izvori: polja portala (index.hr, Njuškalo, nekretnine.hr), rečenice iz opisa i
okućnica. Ništa se ne odbija – kad parkinga nema ili nije naveden, oglas stiže s ⚠
(osim kad je okućnica dovoljna)."""

import re

from .models import HOUSE, Listing
from .risks import sentences
from .text import areas_in_text, fmt_m2, fold

# Nad fold() tekstom (mala slova, bez dijakritika).
_NEGATIVE = re.compile(
    r"\b(nema|bez)\s+(vlastit\w*\s+|privatn\w*\s+|osigurano\w*\s+)?(parking\w*|parkirn\w*|garaz\w*|mogucnost\w* parkiranja|mjesta za (auto|parkiranje))"
    r"|\bparking\w*\s+(nije|ne)\s+(moguc|postoji|osiguran)"
    r"|\bpjesack\w* (pristup|stazom|putem)|\bbez kolnog (pristupa|prilaza)|\bnema kolnog (pristupa|prilaza)")
_PUBLIC = re.compile(r"\b(javn\w*|gradsk\w*|ulicn\w*)\s+parking\w*|\bparking\w*\s+(na ulici|na javnoj|u blizini|uz cestu|u ulici)"
                     r"|\bparkiranje\s+(na ulici|na javnoj|uz cestu|u blizini)")
_POSITIVE = [
    (re.compile(r"\bgaraz\w*"), "garaža"),
    (re.compile(r"\bnadstresnic\w*\s+za\s+(auto|automobil|vozil)\w*|\bcarport"), "nadstrešnica za auto"),
    (re.compile(r"\b(parkirn\w*|parking)\s+mjest\w*|\bmjest\w*\s+za\s+(parkiranje|auto|automobil|vozil)\w*"), "parkirno mjesto"),
    (re.compile(r"\bparkiralist\w*"), "parkiralište"),
    (re.compile(r"\bparking\w*|\bparkiranj\w*"), "parking"),
]
_PLOT = re.compile(r"\b(okucnic\w*|dvorist\w*|vrt\w*|zemljist\w*|parcel\w*)\b[^.]{0,40}?(\d[\d.,]*\s*(?:m2|m²|m\s?2|čhv|chv))")
MIN_PLOT_M2 = 100   # okućnica od ovoliko m² obično ima mjesta za auto


def plot_from_text(text: str) -> float | None:
    """Okućnica iz opisa ("okućnica 300 m2", "na zemljištu od 600 m²")."""
    for m in _PLOT.finditer(fold(text or "")):
        areas = areas_in_text(m.group(2))
        if areas:
            return areas[0]
    return None


def check(listing: Listing, min_plot: float = MIN_PLOT_M2) -> tuple[str, str]:
    """(redak za obavijest, upozorenje ili "") za kuću; za zemljište ("", "")."""
    if listing.kind != HOUSE:
        return "", ""
    field = str(listing.extra.get("parking") or "").strip()
    if field and field != "0":
        return (f"🚗 parkirnih mjesta: {field}" if field.isdigit() else f"🚗 {field}"), ""
    text = f"{listing.title}. {listing.description or ''}"
    negative = public = positive = ""
    for sentence in sentences(text):
        folded = fold(sentence)
        if _NEGATIVE.search(folded):
            negative = negative or sentence
            continue
        rest = _PUBLIC.sub(" ", folded)    # "vlastiti parking, a gradski parking je 20 m dalje"
        label = next((label for rx, label in _POSITIVE if rx.search(rest)), "")
        if label:
            positive = positive or label
        elif _PUBLIC.search(folded):
            public = public or sentence
    if positive:
        return f"🚗 {positive} (iz opisa)", ""
    plot = listing.plot_area or plot_from_text(listing.description)
    quote = negative or public
    if quote:
        short = quote if len(quote) <= 120 else quote[:117] + "…"
        if plot and plot >= min_plot:
            return f"🚗 okućnica {fmt_m2(plot)}", f"parking: „{short}” – okućnica {fmt_m2(plot)}, provjeri ima li mjesta za auto"
        return "", f"parking: „{short}”"
    if plot and plot >= min_plot:
        return f"🚗 parking nije naveden – okućnica {fmt_m2(plot)}", ""
    if len(listing.description or "") < 80:
        return "🚗 parking: nema podataka (oglas bez opisa)", ""
    if listing.extra.get("opis_skracen"):
        return "🚗 parking nije spomenut u skraćenom opisu – vidi oglas", ""
    small = f" (okućnica {fmt_m2(plot)})" if plot else ""
    return "", f"parking nije naveden{small} – provjeri"
