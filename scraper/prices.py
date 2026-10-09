"""Usporedba cijene oglasa s ostvarenim i traženim cijenama na istom području.

1. Plan približnih vrijednosti (PPV, ISPU): vrijednosti iz ostvarenih prodaja po
   cjenovnim blokovima, tablica po naseljima u data/ppv_naselja.json (izrada:
   tools/ppv_preuzmi.py + tools/build_ppv.py, jednom godišnje): za svako naselje medijan i
   raspon građevinskog zemljišta stambene i mješovite namjene iz svih njegovih blokova.
   Samo za zemljišta (za kuće PPV ne postoji).
2. Medijan traženih €/m² iz svih oglasa iste vrste koje smo vidjeli u zadnjih godinu
   dana (bilo koje cijene – i skuplji od granice, jer i oni čine tržište): po naselju
   ako ih ima barem MIN_N, inače po gradu/općini. Isti oglas na više portala broji se
   jednom. Za zemljišta se broje samo građevinska. Raspon je velik (novogradnja i
   starina), pa je ovo orijentacija, ne procjena.
3. Usporedba s oglasima po kriterijima (nisu odbijeni, cijena i površina u granicama;
   viđeni u zadnjih godinu dana; isti oglas na više portala jednom): koliko je posto
   tih oglasa jeftinije po m² (točno prebrojano, bez pretpostavke o obliku raspodjele),
   na cijelom području i u naselju (premalo oglasa: grad/općina). Uspoređuju se oglasi
   iste vrste, kategorije (kuće za obnovu ili nedovršene zasebno) i razreda površine –
   €/m² jako pada s površinom (kuća od 80 m² oko 3.200 €/m², od 300 m² oko 1.000). Uz
   to medijan (polovica oglasa je jeftinija, polovica skuplja) – isti pokazatelj za
   područje i naselje; pogrešno upisane cijene ga ne pomiču."""

import json
import re
import statistics
from datetime import datetime, timedelta
from pathlib import Path

from .models import HOUSE, LAND, REJECT, Listing
from .text import fmt_eur, fold, plural

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
RANGE_MIN_N = 3      # manje od MIN_N, a barem toliko: umjesto medijana raspon i broj (odluka korisnika 9. 10.)
MAX_AGE_DAYS = 365
# Što je očito pogrešno upisano (cijena najma, površina u arima…) ne ulazi u medijan.
PLAUSIBLE = {HOUSE: ((30, 1500), (300, 20_000)), LAND: ((100, 100_000), (5, 3_000))}
CHEAP, PRICEY, ODD = -0.15, 0.15, -0.45
# Razredi površine (donje granice, m²): izmjereno 7. 10. na 542 kuće i 1.111 zemljišta po
# kriterijima – unutar razreda €/m² je sličan, između razreda nije. Kuća za obnovu je malo
# pa se uspoređuju sve veličine zajedno.
AREA_BANDS = {HOUSE: (70, 100, 130, 170, 250), LAND: (300, 800, 1200, 2500)}
AREA_MIN_N = 10
RENOVATION = "obnova"


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


def _ok(kind: str, price, area, reasons: str = "", title: str = "") -> bool:
    if kind not in PLAUSIBLE or not price or not area:
        return False
    if kind == LAND and ("nije građevinsko" in (reasons or "") or "ali opis spominje građevinsko" in (reasons or "")
                         or "poljopriv" in fold(title or "")):
        return False                     # samo građevinska (poljoprivredno s ⚠ ima daleko niži €/m²)
    (amin, amax), (pmin, pmax) = PLAUSIBLE[kind]
    return amin <= area <= amax and pmin <= price / area <= pmax


def build(rows: list[dict], locator, now: datetime) -> dict:
    """Medijani €/m² po (vrsta, grad/općina, naselje); naselje "" je cijeli grad/općina."""
    since = (now - timedelta(days=MAX_AGE_DAYS)).isoformat()
    rows = [r for r in rows if r.get("jls") and (r.get("last_seen") or "9") >= since
            and _ok(r["kind"], r.get("price"), r.get("area"), r.get("reasons"), r.get("title"))]
    keys = {r.get("key") for r in rows}
    unique = {}
    for r in rows:
        if str(r.get("notified_at") or "").startswith("dup:") and r["notified_at"][4:] in keys:
            continue                     # isti kao drugi oglas (drugi portal): broji se original
        unique.setdefault((r["kind"], r["jls"], round(r["price"], -3), round(r["area"])), r)
    values: dict[str, list[float]] = {}
    for r in unique.values():
        ppm = r["price"] / r["area"]
        values.setdefault(f"{r['kind']}|{r['jls']}|", []).append(ppm)
        place = place_of(locator, r["jls"], r.get("title"), r.get("settlement"))
        if place:
            values.setdefault(f"{r['kind']}|{r['jls']}|{place}", []).append(ppm)
    return {k: {"n": len(v), "med": round(statistics.median(v))} for k, v in values.items() if len(v) >= MIN_N}


def band(kind: str, area, cat: str = "") -> tuple[int, int | None] | None:
    """Razred površine (od, do isključivo; do None = i veće) za usporedbu."""
    edges = AREA_BANDS.get(kind)
    if edges and cat == RENOVATION:
        edges = edges[:1]
    if not edges or not area or area < edges[0]:
        return None
    for lo, hi in zip(edges, (*edges[1:], None)):
        if hi is None or area < hi:
            return lo, hi
    return None


def band_label(kind: str, lo: int, hi: int | None, cat: str = "") -> str:
    if cat == RENOVATION:
        return "kuće za obnovu ili nedovršene"
    what = "kuće" if kind == HOUSE else "zemljišta"
    lo_, hi_ = f"{lo:,}".replace(",", "."), f"{(hi or 1) - 1:,}".replace(",", ".")
    return f"{what} {lo_}–{hi_} m²" if hi else f"{what} od {lo_} m²"


def category(kind: str, title: str = "", stored: str | None = None) -> str:
    """Kategorija za usporedbu: kuća "obnova" (za obnovu, starina, ruševina, nedovršena) ili ""
    (useljiva; zemljišta). Iz baze (prepoznato i u opisu), za starije zapise iz naslova."""
    from .filters import not_ready
    if kind != HOUSE:
        return ""
    if stored:
        return stored
    return RENOVATION if not_ready(fold(title)) else ""


def signature(kind: str, jls: str | None, price: float, area: float) -> str:
    """Isti oglas na više portala: ista vrsta, grad/općina, cijena (na 1.000 €) i površina."""
    return f"{kind}|{jls}|{round(price, -3):.0f}|{round(area)}"


def build_market(rows: list[dict], locator, now: datetime, criteria: dict) -> list[list]:
    """Oglasi za usporedbu: [€/m², vrsta, kategorija, površina, grad/općina, naselje, potpis, ključevi].
    Isti oglas na više portala je jedan unos: isti potpis, ili kopija koju je runner
    prepoznao ("dup:K" – isti kao oglas K, i uz malo drugačiju površinu ili cijenu)."""
    since = (now - timedelta(days=MAX_AGE_DAYS)).isoformat()
    unique: dict[str, list] = {}
    by_key: dict[str, list] = {}
    usable = []
    for r in rows:
        limits = criteria.get(r.get("kind")) or {}
        if r.get("status") == REJECT or not limits or not r.get("jls") or (r.get("last_seen") or "9") < since:
            continue
        if not _ok(r["kind"], r.get("price"), r.get("area"), r.get("reasons"), r.get("title")):
            continue
        if r["price"] > limits.get("max_cijena", float("inf")) or r["area"] < limits.get("min_povrsina", 0):
            continue                    # npr. parcelacija: stiže i skuplja, ali ne ulazi u usporedbu
        usable.append(r)

    def add(r: dict, entry: list | None) -> None:
        if entry is None:
            sig = signature(r["kind"], r["jls"], r["price"], r["area"])
            entry = unique.get(sig)
        if entry is None:
            entry = unique[sig] = [round(r["price"] / r["area"]), r["kind"],
                                   category(r["kind"], r.get("title"), r.get("category")), round(r["area"]), r["jls"],
                                   place_of(locator, r["jls"], r.get("title"), r.get("settlement")), sig, []]
        elif r.get("category"):
            entry[2] = r["category"]
        entry[7].append(r.get("key") or "")
        by_key[r.get("key") or ""] = entry

    def original(r: dict) -> str | None:
        mark = str(r.get("notified_at") or "")
        return mark[4:] if mark.startswith("dup:") else None

    copies = [r for r in usable if original(r)]
    for r in usable:
        if not original(r):
            add(r, None)
    while copies:                        # kopija kopije: original dolazi prije
        rest = []
        for r in copies:
            if original(r) in by_key:
                add(r, by_key[original(r)])
            else:
                rest.append(r)
        if len(rest) == len(copies):     # original nije u usporedbi (star, odbijen): kopija sama
            for r in rest:
                add(r, None)
            break
        copies = rest
    return list(unique.values())


def share_below(values: list[float], value: float) -> int:
    """Postotak vrijednosti manjih od zadane (jednake se broje upola)."""
    below = sum(1 for v in values if v < value) + 0.5 * sum(1 for v in values if v == value)
    return round(100 * below / len(values))


def _names(locator) -> dict[str, str]:
    return {fold(n): n for j in locator.jls.values() for n in [*j.settlements, *j.extra]}


def _whole(locator, jls: str) -> str:
    j = locator.by_name(jls)
    return f"{jls} – {'cijeli grad' if j and j.kind == 'grad' else 'cijela općina'}"


def _pct(diff: float) -> int:
    return int(round(abs(diff) * 100 / 5) * 5)


def _rel(ppm: float, ref: float) -> str:
    pct = round((ppm / ref - 1) * 100)
    return "ovaj ≈ isto" if abs(pct) < 3 else f"ovaj {abs(pct)} % {'iznad' if pct > 0 else 'ispod'}"


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


def _blocks(n: int) -> str:
    return plural(n, "blok", "bloka", "blokova")


def median_short(ppm: float, med: float) -> str:
    """Za sažeti redak: prema medijanu PPV-a naselja ("PPV +15 %", "PPV ≈ medijan")."""
    diff = ppm / med - 1
    if abs(diff) < 0.05:
        return "PPV ≈ medijan"
    return f"PPV {'+' if diff > 0 else '−'}{_pct(diff)} %"


def median_note(ppm: float, item: dict, where: str, who: str = "oglas") -> str:
    """"🏛 PPV (Njivice, 3 bloka): građevinsko medijan 188 €/m² (raspon 158–219) – oglas
    15 % iznad medijana" – medijan svih vrijednosti građevinskog zemljišta u blokovima naselja."""
    low, high = (round(v) for v in item["zemljiste"])
    med = round(item["medijan"])
    diff = ppm / med - 1
    rel = f"{who} ≈ medijan" if abs(diff) < 0.05 else \
        f"{who} {_pct(diff)} % {'iznad' if diff > 0 else 'ispod'} medijana"
    if ppm < low * (1 + ODD):
        rel += " – neobično jeftino, provjeri zašto"
    span = "" if low == high else f" (raspon {low:,}–{high:,})".replace(",", ".")
    count = f", {_blocks(item['blokova'])}" if item.get("blokova") else ""
    return f"🏛 PPV ({where}{count}): građevinsko medijan {fmt_eur(med)}/m²{span} – {rel}"


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
        if item.get("medijan"):
            return median_short(listing.price / listing.area, item["medijan"])
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
            if item.get("medijan"):
                n = item.get("naselja") or 0
                places = f", {n} {'naselje' if n % 10 == 1 and n % 100 != 11 else 'naselja'}" if whole and n else ""
                return median_note(ppm, item, f"{where}{places}", who)
            low, high = item["zemljiste"]
            return land_note(ppm, low, high, f"{where}{', raspon naselja' if whole else ''}", who)
        return None


class AskingPrices:
    def __init__(self, locator, groups: dict | None = None, stamp: str = "", market: list | None = None):
        self.locator = locator
        self.groups = groups or {}
        self.market = market or []        # oglasi po kriterijima za usporedbu (build_market)
        self.stamp = stamp
        self.names = _names(locator)

    @classmethod
    def from_rows(cls, rows: list[dict], locator, now: datetime, criteria: dict | None = None) -> "AskingPrices":
        return cls(locator, build(rows, locator, now), now.isoformat(timespec="seconds"),
                   build_market(rows, locator, now, criteria) if criteria else [])

    @classmethod
    def from_file(cls, path: Path, locator) -> "AskingPrices":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(locator, data["grupe"], data.get("izracunato", ""), data.get("usporedivi"))

    def save(self, path: Path) -> None:
        Path(path).write_text(json.dumps({"izracunato": self.stamp, "grupe": self.groups, "usporedivi": self.market},
                                         ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # --- usporedba s oglasima po kriterijima ---

    def _peers(self, listing: Listing, jls: str) -> dict | None:
        """Usporedivi oglasi: iste vrste, kategorije i razreda površine, bez samog oglasa (i
        njegove kopije na drugom portalu). {"podrucje": [...], "mjesto": (gdje, [...])}"""
        if not _ok(listing.kind, listing.price, listing.area) or _agricultural(listing):
            return None
        cat = category(listing.kind, listing.title, listing.extra.get("kategorija"))
        found = band(listing.kind, listing.area, cat)
        if not found:
            return None
        sig = signature(listing.kind, jls, listing.price, listing.area)
        own = {listing.key, *listing.extra.get("blizanci", [])}     # i ista kuća prije sniženja
        same = [m for m in self.market if m[1] == listing.kind and m[2] == cat and band(m[1], m[3], cat) == found
                and m[6] != sig and not own.intersection(m[7])]
        out = {"band": found, "cat": cat, "podrucje": [m[0] for m in same], "mjesto": None, "raspon": None}
        if jls:
            place = place_of(self.locator, jls, listing.title, listing.settlement)
            local = [m[0] for m in same if m[4] == jls and m[5] == place] if place else []
            town = [m[0] for m in same if m[4] == jls]
            here = (self.names.get(place, place.title()), local) if place else None
            whole = (_whole(self.locator, jls), town)
            if len(local) >= MIN_N:
                out["mjesto"] = here
            elif len(town) >= MIN_N:
                out["mjesto"] = whole
            elif len(local) >= RANGE_MIN_N:      # premalo za medijan: raspon (naselje, inače grad/općina)
                out["raspon"] = here
            elif len(town) >= RANGE_MIN_N:
                out["raspon"] = whole
        return out

    def market_notes(self, listing: Listing, jls: str) -> list[str]:
        """Retci za obavijest, npr.
        "📐 Područje, kuće 100–129 m² (119): medijan 2.480 €/m² – ovaj 12 % ispod · skuplji od 31 %"
        "🏘 Njivice, kuće 100–129 m² (12): medijan 2.900 €/m² – ovaj 20 % ispod · skuplji od 18 %"."""
        peers = self._peers(listing, jls)
        if not peers:
            return []
        ppm = listing.price / listing.area
        label = band_label(listing.kind, *peers["band"], peers["cat"])
        lines = []
        if len(peers["podrucje"]) >= AREA_MIN_N:
            values = peers["podrucje"]
            med = statistics.median(values)
            lines.append(f"📐 Područje, {label} ({len(values)}): medijan {fmt_eur(round(med))}/m² – "
                         f"{_rel(ppm, med)} · skuplji od {share_below(values, round(ppm))} %")
        if peers["mjesto"]:
            where, values = peers["mjesto"]
            med = statistics.median(values)
            lines.append(f"🏘 {where}, {label} ({len(values)}): medijan {fmt_eur(round(med))}/m² – "
                         f"{_rel(ppm, med)} · skuplji od {share_below(values, round(ppm))} %")
        elif peers["raspon"]:
            where, values = peers["raspon"]
            low, high = min(values), max(values)
            pos = "ispod najjeftinijeg" if ppm < low else "iznad najskupljeg" if ppm > high else "u rasponu"
            lines.append(f"🏘 {where}, {label} ({len(values)}, premalo za medijan): "
                         f"{fmt_eur(round(low)).removesuffix(' €')}–{fmt_eur(round(high))}/m² – ovaj {pos}")
        return lines

    def market_short(self, listing: Listing, jls: str) -> str | None:
        """Za sažeti redak: "skuplji od 31 % područja, 18 % mjesta"."""
        peers = self._peers(listing, jls)
        if not peers:
            return None
        ppm = round(listing.price / listing.area)
        parts = []
        if len(peers["podrucje"]) >= AREA_MIN_N:
            parts.append(f"{share_below(peers['podrucje'], ppm)} % područja")
        if peers["mjesto"]:
            parts.append(f"{share_below(peers['mjesto'][1], ppm)} % mjesta")
        return f"skuplji od {', '.join(parts)}" if parts else None

    def describe(self, listing: Listing, jls: str) -> tuple[str | None, str | None, str | None]:
        """(redak područja 📐, redak naselja 🏘, sažetak). Bez dovoljno oglasa po kriterijima:
        medijan svih oglasa u naselju (osim za kuće za obnovu – usporedba s useljivima bi zavarala)."""
        notes = self.market_notes(listing, jls)
        if notes:
            return (next((n for n in notes if n.startswith("📐")), None),
                    next((n for n in notes if n.startswith("🏘")), None), self.market_short(listing, jls))
        if category(listing.kind, listing.title, listing.extra.get("kategorija")) == RENOVATION:
            return None, None, None       # medijan svih kuća (i useljivih) bi zavarao
        return None, self.compare(listing, jls), self.short(listing, jls)

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
            return "mjesto ≈ medijan"
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
