"""FINA Očevidnik nekretnina i pokretnina – dnevni CSV izvoz svih predmeta prodaje.

Samo građevinska zemljišta. CSV nema stupac za županiju ili općinu, a opis je
slobodan tekst, pa se lokacija određuje ovako:
1. katastarska općina iz oznake "k.o. …" (tablica u data/locations_extra.yaml
   i popis naselja),
2. nazivi mjesta u opisu, sa svim padežima (scraper/locations.py),
3. nadležni sud kao pomoćni podatak: kod ovrhe je nadležan sud prema mjestu
   nekretnine, kod stečaja (trgovački sud) prema sjedištu tvrtke.
"""

import csv
import hashlib
import io
import re
from datetime import datetime, timedelta

from ..models import LAND, OTHER, Listing
from ..text import areas_in_text, fold, parse_number
from .base import Source

CSV_URL = "https://ponip.fina.hr/ocevidnik-web/preuzmi/csv"
SEARCH_URL = "https://ponip.fina.hr/ocevidnik-web/pretrazivanje/nekretnina"

_KO = re.compile(
    r"(?:\b[kK]\.\s?[oO]\.?|katastarsk\w*\s+općin\w*)\s*:?\s*"
    r"([A-ZČĆŽŠĐ][\w]*(?:(?:\s*-\s*|\s+)(?:[A-ZČĆŽŠĐ][\w]*|na(?=\s+[A-ZČĆŽŠĐ]))){0,3})"
)
_BUILDING = re.compile(r"gradevinsk")
_LAND = re.compile(r"zemljist|cestic|parcel")
_AGRICULTURAL = re.compile(r"poljoprivredn|sumsk|\bsuma\b|oranic|livad|pasnjak|vinograd|maslinik|vocnjak")
_STRUCTURE = re.compile(r"\bkuc[aeiu]\b|obiteljsk\w* kuc|\bstan\b|\bstana\b|stambeno poslovn|poslovn\w* prostor|\bzgrad")

# Sudovi (normalizirani nazivi).
_REGION_COURT = re.compile(r"\bu (rijeci|crikvenici)\b")
_OTHER_AREA_SERVICE = re.compile(r"stalna sluzba u (rabu|malom losinju|delnicama)")
_COMMERCIAL = re.compile(r"trgovack")


def _date(value: str):
    value = (value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def is_active(row: dict, now: datetime) -> bool:
    end = _date(row.get("Datum i vrijeme završetka nadmetanja", ""))
    if end:
        return end >= now - timedelta(days=1)
    decided = _date(row.get("Datum odluke o prodaji", ""))
    return decided is None or decided >= now - timedelta(days=365)


class Fina(Source):
    name = "fina"
    label = "FINA Očevidnik"
    daily = True

    def fetch(self, mode, known_ids):
        resp = self.http.get(CSV_URL)
        text = resp.content.decode("utf-8-sig", errors="replace")
        rows = csv.DictReader(io.StringIO(text), delimiter=";")
        now = datetime.now()
        out = []
        for row in rows:
            if (row.get("Vrsta predmeta prodaje") or "").strip() != "nekretnina":
                continue
            if not is_active(row, now):
                continue
            listing = self.to_listing(row)
            if listing is not None:
                out.append(listing)
        return out

    def court_class(self, court: str) -> str:
        c = fold(court)
        if _OTHER_AREA_SERVICE.search(c):
            return "druga_regija"      # Rab, Lošinj, Gorski kotar
        if _REGION_COURT.search(c):
            return "regija"
        if _COMMERCIAL.search(c):
            return "stecaj_drugdje"
        return "drugdje"

    def locate(self, opis: str) -> tuple[list[str], list[tuple[str, bool]]]:
        """(nazivi k.o., [(grad/općina, uključen)]) iz opisa."""
        ko_names, places = [], []
        for m in _KO.finditer(opis):
            full = m.group(1).strip()
            if any(rx.search(fold(full)) for rx in self.locator.false_phrases):
                ko_names.append(full)  # npr. "Baška Voda" – nije naša Baška
                continue
            words = re.split(r"(\s*-\s*|\s+)", full)
            # Najduži prefiks koji je točno ime k.o., naselja ili općine:
            # "Omišalj-Njivice", pa "Omišalj". Bez djelomičnih pogodaka
            # ("Donje Polje" nije Dobrinjsko naselje Polje).
            for end in range(len(words), 0, -1):
                name = "".join(words[:end]).strip(" -")
                if not name or name.lower() == "na":
                    continue
                key = fold(name)
                hits = [self.locator.cadastral[key]] if key in self.locator.cadastral else self.locator.by_settlement(name)
                if not hits and self.locator.by_name(name):
                    hits = [self.locator.by_name(name)]
                if hits:
                    ko_names.append(name)
                    places.extend((j.name, j.included) for j in hits)
                    break
            else:
                ko_names.append(full)
        if not places:
            places = [(j.name, j.included) for j, _ in self.locator.scan_text(opis)]
        return ko_names, places

    def to_listing(self, row: dict) -> Listing | None:
        opis = (row.get("Opis") or "").strip()
        folded = fold(opis)
        court = (row.get("Nadležno tijelo") or "").strip()
        court_class = self.court_class(court)
        ko_names, places = self.locate(opis)
        ko_names = list(dict.fromkeys(ko_names))
        included = sorted({name for name, inc in places if inc})
        excluded = sorted({name for name, inc in places if not inc})

        # Predmeti bez ikakve veze s regijom ne idu ni u izvještaj. Kod ovrhe je
        # nadležan sud prema mjestu nekretnine, pa ovrha pred sudom izvan regije
        # znači istoimeno mjesto drugdje (Baška Voda, Mošćenica kod Petrinje…).
        if court_class == "drugdje":
            return None
        if court_class not in ("regija", "druga_regija") and not included:
            return None
        if not _LAND.search(folded) and not _BUILDING.search(folded):
            return None

        warnings, reject = [], []
        if _BUILDING.search(folded):
            kind, subtype = LAND, "građevinsko zemljište"
            if _AGRICULTURAL.search(folded):
                warnings.append("opis spominje i poljoprivredno/šumsko zemljište")
            if _STRUCTURE.search(folded):
                warnings.append("opis spominje i objekt (kuću, stan ili zgradu) – provjeri je li to zemljište")
        elif _AGRICULTURAL.search(folded):
            kind, subtype = LAND, "poljoprivredno/šumsko zemljište"
        else:
            kind, subtype = (LAND, "zemljište") if _LAND.search(folded) else (OTHER, "nekretnina")

        municipality = ""
        if included:
            municipality = included[0]
            if len(included) > 1:
                warnings.append(f"opis spominje više mjesta: {', '.join(included)}")
            if excluded:
                warnings.append(f"opis spominje i: {', '.join(excluded)}")
            if court_class == "stecaj_drugdje":
                warnings.append(f"stečaj pred sudom izvan regije ({court}) – provjeri lokaciju")
            elif court_class == "druga_regija":
                warnings.append(f"sud za drugo područje ({court}) – provjeri lokaciju")
        elif excluded:
            municipality = excluded[0]
        elif court_class == "druga_regija":
            reject.append(f"sud za Rab, Lošinj ili Gorski kotar ({court})")
        location_note = ""
        if not included and not excluded:
            names = ", ".join(ko_names)
            location_note = f"lokacija nije prepoznata (k.o. {names})" if names else "lokacija nije prepoznata u opisu"

        price = parse_number(row.get("Početna cijena za nadmetanje")) or parse_number(row.get("Utvrđena vrijednost"))
        areas = areas_in_text(opis)
        if len(areas) > 1:
            warnings.append(f"više površina u opisu: {', '.join(f'{a:,.0f}'.replace(',', '.') for a in areas)} m² – uzeta najveća")

        details = [
            ("Nadležno tijelo", court),
            ("Poslovni broj spisa", row.get("Poslovni broj spisa")),
            ("Način prodaje", row.get("Način prodaje")),
            ("Utvrđena vrijednost", row.get("Utvrđena vrijednost")),
            ("Početna cijena", row.get("Početna cijena za nadmetanje")),
            ("Početak nadmetanja", row.get("Datum i vrijeme početka nadmetanja")),
            ("Završetak nadmetanja", row.get("Datum i vrijeme završetka nadmetanja")),
            ("Jamčevina", row.get("Iznos jamčevine")),
            ("Razgledavanje", row.get("Razgledavanje")),
        ]
        detail_text = "\n".join(f"{k}: {v}" for k, v in details if v)
        ident = "|".join([court, row.get("Poslovni broj spisa") or "", row.get("ID nadmetanja") or "", opis[:200]])
        place = ", ".join(f"k.o. {k}" for k in ko_names) or (municipality or "lokacija nepoznata")
        return Listing(
            source=self.name,
            source_id=hashlib.sha1(ident.encode("utf-8")).hexdigest()[:16],
            url=SEARCH_URL,
            title=f"FINA: {subtype}, {place} ({row.get('Poslovni broj spisa') or 'bez broja spisa'})",
            kind=kind,
            subtype=subtype,
            price=price,
            area=max(areas) if areas else None,
            county="",
            municipality=municipality,
            location_text="; ".join(f"k.o. {k}" for k in ko_names),
            description=f"{opis}\n\n{detail_text}",
            extra={"warnings": warnings, "reject": reject, "location_note": location_note, "ukupna_cijena": True,
                   "sud": court, "spis": row.get("Poslovni broj spisa") or ""},
        )

    def search_links(self):
        return [("Očevidnik – pretraga nekretnina", SEARCH_URL)]
