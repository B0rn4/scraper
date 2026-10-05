"""Odluka za svaki oglas: prolazi, upozorenje (⚠) ili odbijen, uvijek s razlogom."""

import re

from . import parking, risks
from .locations import Locator
from .models import HOUSE, LAND, PASS, REJECT, WARN, Decision, Listing
from .text import fmt_eur, fmt_m2, fold

# Vrste s portala (normalizirane) koje sigurno nisu cijela samostojeća kuća.
_HOUSE_SUBTYPE_REJECT = [
    (re.compile(r"\bdvojn"), "dvojna kuća"),
    (re.compile(r"\bu nizu\b|\bnizu\b"), "kuća u nizu"),
    (re.compile(r"\bpolu ?ugraden"), "poluugrađena (dvojna) kuća"),
    (re.compile(r"\bstan\b|\bstanovi\b|\bapartman\b|\bgarsonijer"), "stan"),
    (re.compile(r"\betaz"), "etaža kuće"),
]
_HOUSE_SUBTYPE_WARN = [
    (re.compile(r"poslovno stambena|stambena zgrada|zgrada"), "stambena ili poslovno-stambena zgrada"),
]

# Fraze u naslovu koje znače dio kuće ili kuću koja nije samostojeća.
_TITLE_REJECT = [
    (re.compile(r"\bdvojn\w* (kuc|objekt)"), "dvojna kuća"),
    (re.compile(r"\bkuc\w* u nizu\b"), "kuća u nizu"),
    (re.compile(r"\b(polovic\w*|polovin\w*|pola|dio|dijel\w*) (obiteljske )?kuc"), "dio kuće"),
    (re.compile(r"\b(etaz\w*|kat|prizemlje|visoko prizemlje|potkrovlje) (obiteljske )?kuc"), "etaža kuće"),
    (re.compile(r"\bstan u (obiteljskoj )?kuc"), "stan u kući"),
]
_TEXT_WARN = [
    (re.compile(r"\bdvojn\w* (kuc|objekt)|\bkuc\w* u nizu\b"), "opis spominje dvojnu kuću ili kuću u nizu"),
    (re.compile(r"\b(polovic\w*|polovin\w*|pola) kuc|\betaz\w* kuc"), "opis spominje dio kuće ili etažu"),
]
_RENOVATION = re.compile(
    r"za obnov|za adaptacij|potrebn\w* (obnov|adaptacij|renovacij)|starin|rusevin|za rusenje|zapust"
)
_BUILDING_LAND = re.compile(r"gradevinsk")
_AGRICULTURAL = re.compile(r"poljoprivredn|sumsk|oranic|livad|pasnjak|vinograd|maslinik|vocnjak")


def evaluate(listing: Listing, criteria: dict, locator: Locator) -> Decision:
    reasons: list[str] = []
    warnings: list[str] = list(listing.extra.get("warnings", []))
    reasons.extend(listing.extra.get("reject", []))
    near_miss_only = not reasons
    pct = criteria.get("za_dlaku_posto", 15) / 100

    subtype = fold(listing.subtype)
    title = fold(listing.title)
    text = fold(f"{listing.title} {listing.description}")

    # --- vrsta nekretnine ---
    if listing.kind == HOUSE:
        limits = criteria["kuca"]
        for rx, label in _HOUSE_SUBTYPE_REJECT:
            if rx.search(subtype):
                reasons.append(f"{label} (vrsta: {listing.subtype})")
                near_miss_only = False
                break
        else:
            for rx, label in _TITLE_REJECT:
                if rx.search(title):
                    reasons.append(f"{label} (naslov)")
                    near_miss_only = False
                    break
            else:
                for rx, label in _HOUSE_SUBTYPE_WARN:
                    if rx.search(subtype):
                        warnings.append(f"{label} – provjeri je li cijela kuća")
                for rx, label in _TEXT_WARN:
                    if rx.search(text):
                        warnings.append(label)
                        break
    elif listing.kind == LAND:
        limits = criteria["zemljiste"]
        land_type = subtype or title  # index.hr ne daje vrstu zemljišta, samo naslov
        shown = listing.subtype or "naslov"
        if _BUILDING_LAND.search(land_type):
            if _AGRICULTURAL.search(land_type):
                warnings.append(f"mješovito zemljište ({listing.subtype or listing.title})")
        elif _AGRICULTURAL.search(land_type):
            if _BUILDING_LAND.search(text):
                warnings.append(f"{listing.subtype or 'poljoprivredno'}, ali opis spominje građevinsko")
            else:
                reasons.append(f"nije građevinsko ({shown})")
                near_miss_only = False
        elif not _BUILDING_LAND.search(text):
            warnings.append("vrsta zemljišta nije navedena")
    else:
        return Decision(REJECT, [f"nije kuća ni zemljište ({listing.subtype or 'nepoznato'})"])

    # --- lokacija ---
    loc = locator.resolve(
        municipality=listing.municipality,
        settlement=listing.settlement,
        county=listing.county,
        text=" ".join(filter(None, [listing.location_text, listing.title])),
    )
    jls_name = loc.jls.name if loc.jls else ""
    if loc.included is False:
        reasons.append(f"lokacija nije na popisu ({jls_name or loc.evidence})")
        near_miss_only = False
    elif loc.included is None:
        warnings.append(listing.extra.get("location_note") or loc.evidence)
    elif loc.ambiguous:
        warnings.append(f"lokacija nesigurna – {loc.evidence}")
    if loc.included:
        place_text = " ".join(filter(None, [listing.location_text, listing.title]))
        found = locator.settlement_row(jls_name, listing.settlement, place_text)
        if found:
            row, exact = found
            listing.extra["mjere"] = {"naselje": row["naziv"], "tocno": exact, "more_km": row["more_km"],
                                      "rijeka_min": row["rijeka_min"], "zagreb_min": row["zagreb_min"]}
        verdict = locator.settlement_verdict(jls_name, listing.settlement, place_text)
        if verdict and verdict[0] == REJECT:
            reasons.append(verdict[1])
            near_miss_only = False
        elif verdict:
            warnings.append(verdict[1])

    # --- opasni izrazi (pravni problemi, pristup) ---
    for rule, sentence in risks.scan(f"{listing.title}. {listing.description}", listing.source):
        if rule.reject:
            reasons.append(f"{rule.label}: „{sentence}”")
            near_miss_only = False
        else:
            warnings.append(f"{rule.label}: „{sentence}”")

    # --- parking (kuća: parkirno mjesto ili dovoljno okućnice) ---
    if listing.kind == HOUSE:
        line, warning = parking.check(listing, limits.get("okucnica_za_parking_m2", parking.MIN_PLOT_M2))
        listing.extra["parking_redak"] = line
        if warning:
            warnings.append(warning)

    # --- cijena ---
    price = listing.price if listing.price and listing.price > 1000 else None
    if listing.extra.get("ukupna_cijena") and listing.price:
        price = listing.price  # FINA: početna cijena je uvijek ukupna, i kad je mala
    elif price is None and listing.price and listing.price > 100 and listing.area:
        # Cijena između 100 i 1.000 € je obično cijena po m². Do 100 € (1, 10, 100)
        # portali koriste kao zamjenu za "cijena na upit".
        price = listing.price * listing.area
        warnings.append(f"cijena {fmt_eur(listing.price)} je vjerojatno po m² – ukupno ≈ {fmt_eur(price)}")
    if price is None:
        warnings.append("cijena nije navedena")
    elif price > limits["max_cijena"]:
        reasons.append(f"cijena {fmt_eur(price)} > {fmt_eur(limits['max_cijena'])}")
        if price > limits["max_cijena"] * (1 + pct):
            near_miss_only = False

    # --- površina ---
    if listing.area is None:
        warnings.append("površina nije navedena")
    elif listing.area < limits["min_povrsina"]:
        reasons.append(f"površina {fmt_m2(listing.area)} < {fmt_m2(limits['min_povrsina'])}")
        if listing.area < limits["min_povrsina"] * (1 - pct):
            near_miss_only = False

    if listing.kind == HOUSE and _RENOVATION.search(text):
        listing.extra["za_obnovu"] = True

    if reasons:
        return Decision(REJECT, reasons, warnings, jls_name, loc.evidence, near_miss=near_miss_only)
    if warnings:
        return Decision(WARN, [], warnings, jls_name, loc.evidence)
    return Decision(PASS, [], [], jls_name, loc.evidence)
