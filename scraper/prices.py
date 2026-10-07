"""Usporedba cijene oglasa s ostvarenim i traženim cijenama na istom području.

1. Plan približnih vrijednosti (PPV, ISPU): vrijednosti iz ostvarenih prodaja po
   cjenovnim blokovima, tablica po naseljima u data/ppv_naselja.json (izrada:
   tools/ppv_preuzmi.py + tools/build_ppv.py, jednom godišnje). Postoji za zemljišta i stanove, ne za
   kuće – za kuće se pokazuje vrijednost stanova slične veličine, kao orijentacija.
2. Medijan traženih €/m² iz svih oglasa iste vrste koje smo vidjeli u zadnjih godinu
   dana (bilo koje cijene – i skuplji od granice, jer i oni čine tržište): po naselju
   ako ih ima barem MIN_N, inače po gradu/općini. Isti oglas na više portala broji se
   jednom. Za zemljišta se broje samo građevinska. Raspon je velik (novogradnja i
   starina), pa je ovo orijentacija, ne procjena.
3. Prosjek €/m² cijelog područja: oglasi koji odgovaraju kriterijima (nisu odbijeni,
   cijena i površina u granicama), po razredima površine – €/m² jako pada s površinom
   (kuća od 80 m² oko 3.200 €/m², od 300 m² oko 1.000). Prosjek bez 10 % najjeftinijih
   i 10 % najskupljih, da ga pogrešno upisane cijene ne pomaknu."""

import json
import re
import statistics
from datetime import datetime, timedelta
from pathlib import Path

from .models import HOUSE, LAND, REJECT, Listing
from .text import fmt_eur, fold

PPV_FILE = Path(__file__).resolve().parent.parent / "data" / "ppv_naselja.json"


def _ppv_year(path: Path = PPV_FILE) -> int:
    """Godina PPV-a u tablici (osvježava se jednom godišnje, tools/ppv_preuzmi.py)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return int(data.get("godina") or re.search(r"(\d{4})\.?$", data.get("izvor", "")).group(1))
    except (OSError, ValueError, AttributeError):
        return 2026


PPV_YEAR = _ppv_year()
MIN_N = 8
MAX_AGE_DAYS = 365
# Što je očito pogrešno upisano (cijena najma, površina u arima…) ne ulazi u medijan.
PLAUSIBLE = {HOUSE: ((30, 1500), (300, 20_000)), LAND: ((100, 100_000), (5, 3_000))}
CHEAP, PRICEY, ODD = -0.15, 0.15, -0.45
# Razredi površine za prosjek područja (donje granice, m²): izmjereno 7. 10. na 542 kuće
# i 1.111 zemljišta po kriterijima – unutar razreda €/m² je sličan, između razreda nije.
AREA_BANDS = {HOUSE: (70, 100, 130, 170, 250), LAND: (300, 800, 1200, 2500)}
AREA_MIN_N = 10
TRIM = 0.1


def place_of(locator, jls: str, title: str, settlement: str) -> str:
    """Naselje oglasa (normalizirani naziv) unutar grada/općine, ili "" ako nije jednoznačno.
    Naziv samog grada/općine ("Krk") se ne broji: može značiti i grad i cijeli otok."""
    if settlement:
        key = fold(settlement)
        key = locator.aliases.get(key, key)
        if locator.by_name(key) is None and any(j.name == jls for j in locator.by_settlement(key)):
            return key
    found = {name for j, name in locator.scan_names(f"{title or ''}, {settlement or ''}")
             if j.name == jls and locator.by_name(name) is None and name != "centar"}
    return found.pop() if len(found) == 1 else ""


def _agricultural(listing: Listing) -> bool:
    """Zemljište koje oglas zove poljoprivrednim (stiže s ⚠ kad opis spominje građevinsko)."""
    return listing.kind == LAND and "poljopriv" in fold(f"{listing.subtype} {listing.title}")


def _ok(kind: str, price, area, reasons: str = "") -> bool:
    if kind not in PLAUSIBLE or not price or not area:
        return False
    if kind == LAND and "nije građevinsko" in (reasons or ""):
        return False
    (amin, amax), (pmin, pmax) = PLAUSIBLE[kind]
    return amin <= area <= amax and pmin <= price / area <= pmax


def build(rows: list[dict], locator, now: datetime) -> dict:
    """Medijani €/m² po (vrsta, grad/općina, naselje); naselje "" je cijeli grad/općina."""
    since = (now - timedelta(days=MAX_AGE_DAYS)).isoformat()
    unique = {}
    for r in rows:
        if not r.get("jls") or (r.get("last_seen") or "9") < since:
            continue
        if not _ok(r["kind"], r.get("price"), r.get("area"), r.get("reasons")):
            continue
        unique.setdefault((r["kind"], r["jls"], round(r["price"], -3), round(r["area"])), r)
    values: dict[str, list[float]] = {}
    for r in unique.values():
        ppm = r["price"] / r["area"]
        values.setdefault(f"{r['kind']}|{r['jls']}|", []).append(ppm)
        place = place_of(locator, r["jls"], r.get("title"), r.get("settlement"))
        if place:
            values.setdefault(f"{r['kind']}|{r['jls']}|{place}", []).append(ppm)
    return {k: {"n": len(v), "med": round(statistics.median(v))} for k, v in values.items() if len(v) >= MIN_N}


def band(kind: str, area) -> tuple[int, int | None] | None:
    """Razred površine (od, do isključivo; do None = i veće) za prosjek područja."""
    edges = AREA_BANDS.get(kind)
    if not edges or not area or area < edges[0]:
        return None
    for lo, hi in zip(edges, (*edges[1:], None)):
        if hi is None or area < hi:
            return lo, hi
    return None


def band_label(kind: str, lo: int, hi: int | None) -> str:
    what = "kuće" if kind == HOUSE else "zemljišta"
    return f"{what} {lo}–{hi - 1} m²" if hi else f"{what} od {lo} m²"


def trimmed_mean(values: list[float], part: float = TRIM) -> float:
    values = sorted(values)
    cut = int(len(values) * part)
    kept = values[cut:len(values) - cut] or values
    return sum(kept) / len(kept)


def build_area(rows: list[dict], now: datetime, criteria: dict) -> dict:
    """Prosjek €/m² cijelog područja po (vrsta, razred površine) iz oglasa po kriterijima."""
    since = (now - timedelta(days=MAX_AGE_DAYS)).isoformat()
    unique = {}
    for r in rows:
        limits = criteria.get(r.get("kind")) or {}
        if r.get("status") == REJECT or not limits or (r.get("last_seen") or "9") < since:
            continue
        if not _ok(r["kind"], r.get("price"), r.get("area"), r.get("reasons")):
            continue
        if r["price"] > limits.get("max_cijena", float("inf")) or r["area"] < limits.get("min_povrsina", 0):
            continue                    # npr. parcelacija: stiže i skuplja, ali ne ulazi u prosjek
        unique.setdefault((r["kind"], r.get("jls"), round(r["price"], -3), round(r["area"])), r)
    values: dict[tuple, list[float]] = {}
    for r in unique.values():
        found = band(r["kind"], r["area"])
        if found:
            values.setdefault((r["kind"], *found), []).append(r["price"] / r["area"])
    return {f"{kind}|{lo}": {"od": lo, "do": hi, "n": len(v), "prosjek": round(trimmed_mean(v))}
            for (kind, lo, hi), v in values.items() if len(v) >= AREA_MIN_N}


def _names(locator) -> dict[str, str]:
    return {fold(n): n for j in locator.jls.values() for n in [*j.settlements, *j.extra]}


def _whole(locator, jls: str) -> str:
    j = locator.by_name(jls)
    return f"{jls} – {'cijeli grad' if j and j.kind == 'grad' else 'cijela općina'}"


def _pct(diff: float) -> int:
    return int(round(abs(diff) * 100 / 5) * 5)


def land_short(ppm: float, low: float, high: float) -> str:
    """Za sažeti redak: "PPV u rasponu", "PPV +15 %" (iznad gornje), "PPV −30 %" (ispod donje)."""
    if ppm > high * 1.05:
        return f"PPV +{_pct(ppm / high - 1)} %"
    if ppm < low * 0.95:
        return f"PPV −{_pct(ppm / low - 1)} %"
    return "PPV u rasponu"


def land_note(ppm: float, low: float, high: float, where: str, who: str = "oglas") -> str:
    """Cijena zemljišta prema rasponu PPV-a za građevinsko zemljište (who: "oglas" ili
    "početna cijena" za natječaj)."""
    low, high = round(low), round(high)
    if ppm > high * 1.05:
        rel = f"{who} {_pct(ppm / high - 1)} % iznad gornje"
    elif ppm < low * 0.95:
        rel = f"{who} {_pct(ppm / low - 1)} % ispod donje"
        if ppm < low * (1 + ODD):
            rel += " – neobično jeftino, provjeri zašto"
    else:
        rel = f"{who} u rasponu"
    span = f"{fmt_eur(low)}/m²" if low == high else f"{low:,}–{high:,} €/m²".replace(",", ".")
    return f"🏛 PPV ({where}): građevinsko {span} – {rel}"


class Ppv:
    """Plan približnih vrijednosti po naseljima (ostvarene cijene)."""
    def __init__(self, locator, path: Path = PPV_FILE):
        self.locator = locator
        data = json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else {}
        self.places = data.get("naselja", {})
        self.towns = data.get("gradovi_opcine", {})
        self.names = _names(locator)

    def short(self, listing: Listing, jls: str) -> str | None:
        """Za sažeti redak, samo za zemljišta."""
        if listing.kind != LAND or not jls or not _ok(listing.kind, listing.price, listing.area) or _agricultural(listing):
            return None
        place = place_of(self.locator, jls, listing.title, listing.settlement)
        item = (self.places.get(jls, {}).get(place) if place else None) or self.towns.get(jls)
        if not item or not item.get("zemljiste"):
            return None
        return land_short(listing.price / listing.area, *item["zemljiste"])

    def note(self, listing: Listing, jls: str, who: str = "oglas") -> str | None:
        """Samo za zemljišta (za kuće PPV ne postoji; vrijednost stanova je zavaravala), npr.
        "🏛 PPV (Njivice): građevinsko 158–219 €/m² – oglas 15 % iznad gornje"."""
        if not jls or not _ok(listing.kind, listing.price, listing.area) or _agricultural(listing):
            return None
        place = place_of(self.locator, jls, listing.title, listing.settlement)
        item = self.places.get(jls, {}).get(place) if place else None
        where = self.names.get(place, place.title()) if item else ""
        whole = not item
        if whole:
            item, where = self.towns.get(jls), _whole(self.locator, jls)
        if not item:
            return None
        ppm = listing.price / listing.area
        if listing.kind == LAND and item.get("zemljiste"):
            low, high = item["zemljiste"]
            return land_note(ppm, low, high, f"{where}{', raspon naselja' if whole else ''}", who)
        return None


class AskingPrices:
    def __init__(self, locator, groups: dict | None = None, stamp: str = "", area: dict | None = None):
        self.locator = locator
        self.groups = groups or {}
        self.area = area or {}          # prosjek cijelog područja po razredu površine
        self.stamp = stamp
        self.names = _names(locator)

    @classmethod
    def from_rows(cls, rows: list[dict], locator, now: datetime, criteria: dict | None = None) -> "AskingPrices":
        return cls(locator, build(rows, locator, now), now.isoformat(timespec="seconds"),
                   build_area(rows, now, criteria) if criteria else {})

    @classmethod
    def from_file(cls, path: Path, locator) -> "AskingPrices":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(locator, data["grupe"], data.get("izracunato", ""), data.get("podrucje"))

    def save(self, path: Path) -> None:
        Path(path).write_text(json.dumps({"izracunato": self.stamp, "grupe": self.groups, "podrucje": self.area},
                                         ensure_ascii=False), encoding="utf-8")

    def _area_stat(self, listing: Listing) -> tuple[dict, float] | None:
        if not _ok(listing.kind, listing.price, listing.area) or _agricultural(listing):
            return None
        found = band(listing.kind, listing.area)
        stat = self.area.get(f"{listing.kind}|{found[0]}") if found else None
        return (stat, listing.price / listing.area / stat["prosjek"] - 1) if stat else None

    def area_note(self, listing: Listing) -> str | None:
        """Redak za obavijest: prosjek €/m² cijelog područja za oglase iste vrste i slične
        površine, npr. "📐 Prosjek područja, kuće 100–129 m² (113 oglasa): 2.500 €/m² – ovaj 12 % ispod"."""
        found = self._area_stat(listing)
        if not found:
            return None
        stat, diff = found
        pct = round(diff * 100)
        rel = "ovaj ≈ prosjek" if abs(pct) < 3 else f"ovaj {abs(pct)} % {'iznad' if pct > 0 else 'ispod'}"
        return (f"📐 Prosjek područja, {band_label(listing.kind, stat['od'], stat['do'])} ({stat['n']} oglasa): "
                f"{fmt_eur(stat['prosjek'])}/m² – {rel}")

    def area_short(self, listing: Listing) -> str | None:
        """Za sažeti redak: "područje −12 %"."""
        found = self._area_stat(listing)
        if not found:
            return None
        pct = round(found[1] * 100)
        return "područje ≈ prosjek" if abs(pct) < 3 else f"područje {'+' if pct > 0 else '−'}{abs(pct)} %"

    def _stat(self, listing: Listing, jls: str) -> tuple[dict, str] | None:
        if not jls or not _ok(listing.kind, listing.price, listing.area) or _agricultural(listing):
            return None
        place = place_of(self.locator, jls, listing.title, listing.settlement)
        stat = self.groups.get(f"{listing.kind}|{jls}|{place}") if place else None
        where = self.names.get(place, place.title()) if stat else ""
        if not stat:
            stat = self.groups.get(f"{listing.kind}|{jls}|")
            where = _whole(self.locator, jls)
        return (stat, where) if stat else None

    def estimate(self, listing: Listing, jls: str) -> tuple[float, float, str] | None:
        """Za "cijenu na upit": (površina × medijan traženih €/m², medijan, gdje)."""
        if not jls or not listing.area or listing.kind not in (HOUSE, LAND) or _agricultural(listing):
            return None
        place = place_of(self.locator, jls, listing.title, listing.settlement)
        stat = self.groups.get(f"{listing.kind}|{jls}|{place}") if place else None
        where = self.names.get(place, place.title()) if stat else ""
        if not stat:
            stat, where = self.groups.get(f"{listing.kind}|{jls}|"), _whole(self.locator, jls)
        return (listing.area * stat["med"], stat["med"], where) if stat else None

    def short(self, listing: Listing, jls: str) -> str | None:
        """Za sažeti redak: "mjesto −25 %" (prema medijanu traženih u naselju ili gradu/općini)."""
        found = self._stat(listing, jls)
        if not found:
            return None
        diff = listing.price / listing.area / found[0]["med"] - 1
        if abs(diff) < 0.1:
            return "mjesto ≈ prosjek"
        return f"mjesto {'+' if diff > 0 else '−'}{_pct(diff)} %"

    def compare(self, listing: Listing, jls: str) -> str | None:
        """Redak za obavijest, npr. "💰 25 % ispod medijana traženih (Njivice: 3.550 €/m², 40 oglasa)"."""
        found = self._stat(listing, jls)
        if not found:
            return None
        stat, where = found
        diff = listing.price / listing.area / stat["med"] - 1
        pct = _pct(diff)
        basis = f"({where}: {fmt_eur(stat['med'])}/m², {stat['n']} oglasa)"
        if diff <= ODD and listing.kind == HOUSE:   # zemljište: prema donjoj granici PPV-a
            return f"💰 {pct} % ispod medijana traženih {basis} – neobično jeftino, provjeri zašto"
        if diff <= CHEAP:
            return f"💰 {pct} % ispod medijana traženih {basis}"
        if diff >= PRICEY:
            return f"💸 {pct} % iznad medijana traženih {basis}"
        return f"📊 oko medijana traženih {basis}"
