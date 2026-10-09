"""Odluka za svaki oglas: prolazi, upozorenje (⚠) ili odbijen, uvijek s razlogom."""

import re
import unicodedata

from . import parking, risks
from .locations import LocationResult, Locator
from .models import HOUSE, LAND, PASS, REJECT, WARN, Decision, Listing
from .text import areas_in_text, fmt_eur, fmt_m2, fold

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
# Bazen (korisnik 7. 10.: kuću s bazenom ne želi). Naslov ili vrsta → odbija se; opis → ⚠
# (opis zna spominjati i "mogućnost izgradnje bazena", "gradski bazen u blizini").
_POOL = re.compile(r"\bbazen\w*|\bpool\b")
_NO_POOL = re.compile(r"\bbez bazen|mogucnost\w* (izgradnje |gradnje |izvedbe )?(i )?bazen|(prostor|mjest|predviden)\w* "
                      r"(\w+ )?(za )?bazen|blizin\w* (\w+ )?bazen|gradsk\w* bazen|javn\w* bazen|bazen\w* u (naselju|blizini)")
_TEXT_WARN = [
    (re.compile(r"\bdvojn\w* (kuc|objekt)|\bkuc\w* u nizu\b"), "opis spominje dvojnu kuću ili kuću u nizu"),
    (re.compile(r"\b(polovic\w*|polovin\w*|pola) kuc|\betaz\w* kuc"), "opis spominje dio kuće ili etažu"),
]
_RENOVATION = re.compile(
    r"za obnov|za adaptacij|potrebn\w* (obnov|adaptacij|renovacij)|starin(?!\w* stil)|za rusenje|zapust"
)
# Ruševina (odluka korisnika 9. 10.): kuća u ruševnom stanju ili za rušenje se odbija – nije ni
# za obnovu, a njezin €/m² kvari usporedbu cijena. Kad isti oglas kaže da je za obnovu
# (adaptaciju, rekonstrukciju) ili da je useljiva / obnovljena, ostaje (ruševina je onda "za
# obnovu" 🔨 ili nije o kući). Ne računa se ruševina koja nije sama kuća: štala ili pomoćna zgrada
# uz kuću, dodatak ("i kamena ruševina"), nekadašnja ("obnovljena iz ruševine", "na mjestu stare
# ruševine") ili u okolici ("u blizini ruševine utvrde"). "Bez krova" i "urušen" se ne broje
# (parkirno mjesto bez krova, urušen suhozid), ni "zidine" (gradske zidine Krka).
_RUIN = re.compile(r"\brusev(?:in|n|an)\w*|\bza rusenje")
_RUIN_DENIED = re.compile(r"\b(?:ne|nije|nisu|nikako|bez)\s+(?:\w+\s+){0,3}$")
# Ruševina kao dodatak uz kuću ("dvije garsonijere u kući i kamena ruševina", "s ruševinom").
_RUIN_EXTRA = re.compile(r"\b(?:i|te|uz|s|sa|plus|dodatno|kao i)\s+(?:\w+\s+){0,2}$")
_RUIN_ELSEWHERE = re.compile(r"\b(?:iz|od|nekad\w*|bivs\w*|na mjestu|umjesto|u blizini|blizu|pogled\w* na|okruzen\w*)"
                             r"\s+(?:\w+\s+){0,2}$")
_HABITABLE = re.compile(r"\buseljiv|\bobnovljen|\brenoviran|\badaptiran|\brekonstruiran")
_OUTBUILDING = re.compile(r"gospodarsk|pomocn|\bstal[aeiu]\b|\bstaj[aeiu]\b|stalic|sjenik|spremist|drvarnic|pojat"
                          r"|susjed")
_FOR_RENOVATION = re.compile(r"\b(?:za|potrebn\w*|moguc\w*|predviden\w*|idealn\w* za)\s+(?:\w+\s+){0,2}"
                             r"(?:obnov|adaptacij|renovacij|rekonstrukcij)|\b(?:obnovit|renovirat|adaptirat|rekonstruirat)")
# Nijekanje neposredno ispred ("nije potrebna obnova", "bez potrebe za obnovom", "nije
# zapuštena"); "nije useljiva, potrebna obnova" nije nijekanje (riječ između nije s popisa).
_NOT_READY_DENIED = re.compile(r"\b(?:ne|nije|nisu|bez|nema|nimalo)\s+"
                               r"(?:(?:je|bila|bilo|uopce|nimalo|potreb\w*|nuzn\w*)\s+){0,2}$|\bne radi se o\s+$")
# "Cijena na upit": luksuzna nekretnina se prepoznaje po riječima u naslovu i procjeni
# (površina × medijan traženih €/m²). Mjerenje 6. 10. na 12.378 oglasa s cijenom: od
# kuća s takvim riječima i procjenom × 0,4 iznad granice 99 % je stvarno preskupo
# (izgubljeno 7 od 1.389 dobrih); kuća s procjenom × 0,2 iznad granice također (4 od
# 1.389). Za zemljišta samo riječi + procjena × 0,4 (0 izgubljenih); bez riječi
# procjena za zemljišta nije pouzdana (cijene po m² jako variraju).
_LUXURY = re.compile(r"luksuz|luxur|ekskluziv|exclusive|\bvill?a\b|\bvile\b|\bvilu\b|bazen|\bpool\b|infinity|premium"
                     r"|prestiz|wellness|jacuzzi|sauna|panoramsk|first row|prvi red|1 ?red\b|\blux\b")
LUXURY_FACTOR, HUGE_HOUSE_FACTOR = 0.4, 0.2
# Starina, ruševina, nedovršena gradnja (Rohbau): cijena po m² je daleko ispod medijana, pa se
# takva "na upit" ne odbija (mjerenje 6. 10.: 4 od 11 izgubljenih kuća u granici bile su takve).
# "U izgradnji" nije ovdje – tako se oglašavaju i nove luksuzne vile.
_UNFINISHED = re.compile(r"rohbau|roh bau|zapocet\w* gradnj|nedovrsen\w*|siva faza|grub\w* radov")


def _said(pattern: re.Pattern, text: str) -> bool:
    """Izraz se spominje, a ne niječe."""
    return any(not _NOT_READY_DENIED.search(text[max(0, m.start() - 60):m.start()]) for m in pattern.finditer(text))


def _ruin_mentions(folded: str):
    """Spomeni ruševine koji su o samoj kući (ne nijekanje, dodatak, pomoćna zgrada, nekad, okolica)."""
    for m in _RUIN.finditer(folded):
        before = folded[max(0, m.start() - 50):m.start()]
        if _RUIN_DENIED.search(before) or _RUIN_EXTRA.search(before) or _RUIN_ELSEWHERE.search(before) \
                or _OUTBUILDING.search(folded[max(0, m.start() - 60):m.end() + 60]):
            continue
        yield m


def ruin(listing: Listing) -> str:
    """Rečenica koja kaže da je kuća ruševina (izvorni tekst), ili "" – i kad oglas kaže da je za
    obnovu, useljiva ili obnovljena."""
    text = f"{listing.title}. {listing.description}"
    folded = fold(text)
    if _said(_FOR_RENOVATION, folded) or _said(_HABITABLE, folded):
        return ""
    for m in _ruin_mentions(folded):
        sentence = next((s for s in risks.sentences(text) if m.group(0) in fold(s)), m.group(0))
        return sentence if len(sentence) <= 160 else sentence[:157] + "…"
    return ""


# Ruševina na kojoj se može graditi (odluka korisnika 9. 10.): građevinska / lokacijska dozvola,
# projekt, građevinska čestica ili zemljište – stiže kao zemljište (okućnica, granice i usporedba
# zemljišta) s ⚠, a ne odbija se kao ruševina. Nijekanje ("nema građevinske dozvole") i "u postupku"
# se ne broje.
_BUILDABLE = re.compile(
    r"\b(?:gradevinsk|lokacijsk)\w* dozvol\w*|\bdozvol\w* za (?:gradnj|izgradnj|rekonstrukcij)"
    r"|\bidejn\w* (?:rjesenj|projekt)|\bglavn\w* projekt|\bprojekt\w* za (?:gradnj|izgradnj|rekonstrukcij|nov)"
    r"|\bgradevinsk\w* (?:cestic|zemljist|teren|parcel|zon|podrucj)|\bmogucnost\w* (?:gradnj|izgradnj)"
    r"|\bizgradnj\w* nov")
_PENDING = re.compile(r"^.{0,40}\bu postupku|u postupku (?:ishodenj|izdavanj|dobivanj)\w*\s+(?:\w+\s+)?$")
# Gradnja koja nije kuća ("idejno rješenje za gradnju poslovne zgrade", "projekt hotela").
_NOT_A_HOUSE = re.compile(r"poslovn|hotel|zgrad|turistick|apartmansk\w* (?:objekt|kompleks)|stambeno.poslovn")
_PLOT_AREA = re.compile(r"\b(?:okucnic|dvorist|zemljist|parcel|cestic|teren|plac)\w*\b[^.]{0,40}?(\d[\d.,]*\s*(?:m2|m²|m 2))")


def _buildable(folded: str) -> bool:
    for m in _BUILDABLE.finditer(folded):
        if _NOT_READY_DENIED.search(folded[max(0, m.start() - 60):m.start()]) \
                or _PENDING.search(folded[m.end():m.end() + 60]) or _PENDING.search(folded[max(0, m.start() - 60):m.start()]) \
                or _NOT_A_HOUSE.search(folded[m.end():m.end() + 60]):
            continue
        return True
    return False


def ruin_as_land(listing: Listing) -> None:
    """Kuća-ruševina na kojoj se može graditi postaje zemljište: površina je okućnica (iz polja
    ili teksta), vrsta "ruševina na građevinskom zemljištu"; ruševina se pamti za ⚠."""
    if listing.kind != HOUSE:
        return
    broken = ruin(listing)
    text = f"{listing.title}. {listing.description}"
    if not broken or not _buildable(fold(text)):
        return
    plot = listing.plot_area or listing.extra.get("okucnica_ranije")   # ranije: stranica oglasa
    if not plot:
        m = _PLOT_AREA.search(fold(text))
        found = areas_in_text(m.group(1)) if m else []
        plot = found[0] if found else None
    listing.extra["rusevina_kao_zemljiste"] = {"m2": listing.area, "recenica": broken}
    listing.kind, listing.subtype = LAND, "ruševina na građevinskom zemljištu"
    listing.area, listing.plot_area = plot, None
    listing.extra.pop("povrsina_iz_teksta", None)


def needs_renovation(text: str) -> bool:
    """Za obnovu, starina, zapuštena – i ruševina, ako je to sama kuća (ruševna štala uz useljivu
    kuću ne čini kuću "za obnovu")."""
    return _said(_RENOVATION, text) or any(True for _ in _ruin_mentions(text))


def not_ready(text: str) -> bool:
    """Kuća za obnovu, starina, ruševina ili nedovršena gradnja (tekst već prošao fold):
    zasebna kategorija u usporedbi cijena, jer ima daleko niži €/m² od useljive kuće."""
    return needs_renovation(text) or _said(_UNFINISHED, text)


# "Negrađevinsko" i "izvan građevinskog (područja)" nisu građevinsko zemljište.
_BUILDING_LAND = re.compile(r"(?<!\bne)(?<!\bne )(?<!\bizvan )(?<!\bvan )gradevinsk")
_AGRICULTURAL = re.compile(r"poljoprivredn|sumsk|oranic|livad|pasnjak|vinograd|maslinik|vocnjak"
                           r"|\bne ?gradevinsk|\b(izvan|van) gradevinsk")


# Parcelacija (dioba zemljišta na više građevinskih čestica): oglas koji je spominje stiže
# neovisno o cijeni i površini (odluka korisnika 7. 10.). Pravilno "parcelacija", često i
# "parcelizacija", glagoli (parcelirati, isparcelirano), pogreške (percelacija) i engleski.
# Ne "parcela" (= čestica). Tekst je bez dijakritika, s interpunkcijom (granice rečenica).
_PARCEL = re.compile(
    r"p[ae]rcel(?:ac|i?zac|iz|ir|is|l?ing)\w*|\bsubdivi\w*|\bdivided\s+into\s+(?:\w+\s+){0,2}plots"
    r"|\b(?:podjel|podijel|dijeljenj|dijeli|razdijel|razdvoj|diob)\w*\s+(?:\w+\s+){0,3}?na\s+(?:\w+\s+){0,2}?"
    r"(?:parcel|cestic|placev|gradilist)\w*")
# Samo kod zemljišta: "može se podijeliti na dva dijela" (kod kuće bi to bili stanovi).
_PARCEL_LAND = re.compile(r"\b(?:podjel|podijel|dijeljenj|dijeli|razdijel|diob)\w*\s+(?:\w+\s+){0,3}?na\s+"
                          r"(?:\d+|dva|dvije|tri|cetiri|vise|nekoliko)\s+(?:\w+\s+)?dijel\w*")
_PARCEL_NOT_BEFORE = re.compile(r"(?:\bne|\bnije|\bnisu|\bnema|\bbez|\bnemoguc\w*|\bzabranjen\w*|\bonemogucen\w*)"
                                r"\s+(?:\w+\s+){0,3}$")
_PARCEL_NOT_AFTER = re.compile(r"^[\s:–-]*(?:\w+\s+){0,2}?(?:nije|nisu|ne\b|nemoguc|zabranjen)")
_PARCEL_STILL_OK = re.compile(r"problem|prepreka|zapreka|upitn|iskljucen")   # "nema prepreka za parcelaciju"


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", (text or "").lower().replace("đ", "d"))
    return "".join(c for c in text if not unicodedata.combining(c))


def parcelation(listing: Listing) -> str:
    """Rečenica (naslov ili opis) koja spominje parcelaciju, osim nijekanja ("parcelacija nije
    moguća", "bez mogućnosti parcelacije"); prazno ako je nema."""
    patterns = [_PARCEL, _PARCEL_LAND] if listing.kind == LAND else [_PARCEL]
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", f"{listing.title}. {listing.description}"):
        plain = _plain(sentence)
        for pattern in patterns:
            for m in pattern.finditer(plain):
                before, after = plain[:m.start()], plain[m.end():m.end() + 40]
                denied = _PARCEL_NOT_BEFORE.search(before) or _PARCEL_NOT_AFTER.search(after)
                if denied and not _PARCEL_STILL_OK.search(before[-40:] + after):
                    continue
                text = " ".join(sentence.split()).strip(" .")
                return text if len(text) <= 160 else text[:157] + "…"
    return ""


def effective_price(price: float | None, area: float | None, total: bool = False, kind: str = "") -> float | None:
    """Ukupna cijena kakvu treba usporediti s granicom. Do 1.000 € (kuća i do 10.000 € uz
    manje od 50 €/m²) je obično cijena po m²
    → puta površina. Kuća: do 100 € (1, 10, 100) portali pišu umjesto "cijena na upit" →
    None. Zemljište: "100 €" je zamjena za "na upit" (u bazi ~100 oglasa, većinom skupi
    tereni), a 10–99 € je stvarna cijena po m² (15, 22, 45, 55, 60 €/m² u bazi); ispod
    10 € opet zamjena. FINA (total=True): početna cijena je uvijek ukupna."""
    if not price:
        return None
    if total:
        return price
    if price > 1000:
        # Kuća za 1.200 ili 3.000 € uz 180–400 m² (ispod 50 €/m²) – to je cijena po m².
        if kind == HOUSE and area and price < 10_000 and price / area < 50:
            return price * area
        return price
    per_m2 = (price >= 10 and price != 100) if kind == LAND else price > 100
    return price * area if per_m2 and area else None


def evaluate(listing: Listing, criteria: dict, locator: Locator, prices=None, ignore_limits: bool = False) -> Decision:
    """prices (medijani traženih, scraper/prices.py): za procjenu kod "cijene na upit".
    ignore_limits: cijena i površina ne odbijaju (izvori: vrijedi li otvoriti stranicu oglasa
    zemljišta – opis može spominjati parcelaciju)."""
    ruin_as_land(listing)
    reasons: list[str] = []
    warnings: list[str] = list(listing.extra.get("warnings", []))
    reasons.extend(listing.extra.get("reject", []))
    if listing.extra.get("rusevina_kao_zemljiste"):
        broken = listing.extra["rusevina_kao_zemljiste"]
        size = f" ({fmt_m2(broken['m2'])})" if broken.get("m2") else ""
        warnings.append(f"ruševina{size} na građevinskom zemljištu ili s dozvolom – stiže kao zemljište "
                        f"(površina je okućnica), provjeri: „{broken['recenica']}”")
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
        broken = ruin(listing)
        if broken:
            reasons.append(f"ruševina: „{broken}”")
            near_miss_only = False
        heading = f"{subtype} {title}"
        if _POOL.search(heading) and not _NO_POOL.search(heading):
            reasons.append("s bazenom (naslov)")
            near_miss_only = False
        elif _POOL.search(text) and not _NO_POOL.search(text):
            warnings.append("opis spominje bazen")
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
    if listing.extra.get("samo_pgz") and listing.settlement and not locator.knows(listing.settlement):
        # Portal pokriva i druge županije, a daje samo naselje: naselje izvan PGŽ-a znači
        # oglas izvan područja, i kad se naziv iz naslova poklapa s nekim našim mjestom.
        loc = LocationResult(None, False, f"mjesto izvan PGŽ-a: {listing.settlement}")
    else:
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
                                      "rijeka_min": row["rijeka_min"]}
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

    # --- cijena i površina: kod parcelacije ne odbijaju (oglas stiže), nego se navode ---
    parcel = parcelation(listing) or ("opis oglasa spominje parcelaciju" if listing.extra.get("parcelacija_ranije") else "")
    if parcel:
        listing.extra["parcelacija"] = parcel
    else:
        listing.extra.pop("parcelacija", None)
    limit_reasons: list[str] = []

    # --- cijena ---
    price = effective_price(listing.price, listing.area, bool(listing.extra.get("ukupna_cijena")), listing.kind)
    if price is not None and price != listing.price:
        warnings.append(f"cijena {fmt_eur(listing.price)} je vjerojatno po m² – ukupno ≈ {fmt_eur(price)}")
    if price is None:
        estimate = prices.estimate(listing, jls_name) if prices is not None and jls_name else None
        if estimate:
            value, med, where = estimate
            basis = f"procjena ≈ {fmt_eur(value)} (medijan traženih {where}: {fmt_eur(med)}/m²)"
            # Luksuz iz naslova ili opisa ("Obiteljska kuća Kostrena", a u opisu "luksuzna vila").
            luxury = bool(_LUXURY.search(fold(f"{listing.subtype} {listing.title} {listing.description}")))
            limit = limits["max_cijena"]
            unfinished = not_ready(text)
            if not unfinished and ((luxury and value * LUXURY_FACTOR > limit)
                                   or (listing.kind == HOUSE and value * HUGE_HOUSE_FACTOR > limit)):
                limit_reasons.append(f"cijena na upit – {'luksuzna, ' if luxury else ''}{basis}")
                near_miss_only = False
            else:
                warnings.append(f"cijena na upit – {basis}")
        else:
            warnings.append("cijena nije navedena")
    elif price > limits["max_cijena"]:
        limit_reasons.append(f"cijena {fmt_eur(price)} > {fmt_eur(limits['max_cijena'])}")
        if price > limits["max_cijena"] * (1 + pct):
            near_miss_only = False

    # --- površina ---
    if not listing.area:  # 0 je na nekim portalima prazno polje, ne stvarna površina
        warnings.append("površina nije navedena")
    elif listing.area < limits["min_povrsina"]:
        limit_reasons.append(f"površina {fmt_m2(listing.area)} < {fmt_m2(limits['min_povrsina'])}")
        if listing.area < limits["min_povrsina"] * (1 - pct):
            near_miss_only = False

    if parcel or ignore_limits:
        warnings.extend(f"{r} – stiže jer spominje parcelaciju" if parcel else r for r in limit_reasons)
    else:
        reasons.extend(limit_reasons)

    if listing.kind == HOUSE and needs_renovation(text):
        listing.extra["za_obnovu"] = True
    if listing.kind == HOUSE and not_ready(text):
        listing.extra["kategorija"] = "obnova"      # pamti se u bazi (usporedba cijena)
    elif listing.kind == HOUSE and listing.description and not (
            listing.extra.get("opis_skracen") or listing.extra.get("samo_popis")):
        listing.extra["kategorija"] = ""            # cijeli opis: useljiva (briše raniju oznaku)

    if reasons:
        return Decision(REJECT, reasons, warnings, jls_name, loc.evidence, near_miss=near_miss_only)
    if warnings:
        return Decision(WARN, [], warnings, jls_name, loc.evidence)
    return Decision(PASS, [], [], jls_name, loc.evidence)
