"""Usporedba tražene cijene s drugim oglasima na istom području.

Medijan cijene po m² iz svih oglasa iste vrste koje smo vidjeli u zadnjih godinu dana
(bilo koje cijene – i skuplji od granice, jer i oni čine tržište): po naselju ako ih
ima barem MIN_N, inače po gradu/općini. Isti oglas na više portala broji se jednom.
Za zemljišta se broje samo građevinska. Tražene cijene nisu ostvarene, a raspon je
velik (novogradnja i starina), pa je ovo orijentacija, ne procjena."""

import json
import statistics
from datetime import datetime, timedelta
from pathlib import Path

from .models import HOUSE, LAND, Listing
from .text import fmt_eur, fold

MIN_N = 8
MAX_AGE_DAYS = 365
# Što je očito pogrešno upisano (cijena najma, površina u arima…) ne ulazi u medijan.
PLAUSIBLE = {HOUSE: ((30, 1500), (300, 20_000)), LAND: ((100, 100_000), (5, 3_000))}
CHEAP, PRICEY, ODD = -0.15, 0.15, -0.45


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


class AskingPrices:
    def __init__(self, locator, groups: dict | None = None, stamp: str = ""):
        self.locator = locator
        self.groups = groups or {}
        self.stamp = stamp
        self.names = {fold(n): n for j in locator.jls.values() for n in [*j.settlements, *j.extra]}

    @classmethod
    def from_rows(cls, rows: list[dict], locator, now: datetime) -> "AskingPrices":
        return cls(locator, build(rows, locator, now), now.isoformat(timespec="seconds"))

    @classmethod
    def from_file(cls, path: Path, locator) -> "AskingPrices":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(locator, data["grupe"], data.get("izracunato", ""))

    def save(self, path: Path) -> None:
        Path(path).write_text(json.dumps({"izracunato": self.stamp, "grupe": self.groups}, ensure_ascii=False),
                              encoding="utf-8")

    def compare(self, listing: Listing, jls: str) -> str | None:
        """Redak za obavijest, npr. "💰 25 % ispod medijana traženih (Njivice: 3.550 €/m², 40 oglasa)"."""
        if not jls or not _ok(listing.kind, listing.price, listing.area):
            return None
        place = place_of(self.locator, jls, listing.title, listing.settlement)
        stat = self.groups.get(f"{listing.kind}|{jls}|{place}") if place else None
        where = self.names.get(place, place.title()) if stat else ""
        if not stat:
            stat = self.groups.get(f"{listing.kind}|{jls}|")
            j = self.locator.by_name(jls)
            where = f"{jls} – {'cijeli grad' if j and j.kind == 'grad' else 'cijela općina'}"
        if not stat:
            return None
        diff = listing.price / listing.area / stat["med"] - 1
        pct = int(round(abs(diff) * 100 / 5) * 5)
        basis = f"({where}: {fmt_eur(stat['med'])}/m², {stat['n']} oglasa)"
        if diff <= ODD:
            return f"💰 {pct} % ispod medijana traženih {basis} – neobično jeftino, provjeri zašto"
        if diff <= CHEAP:
            return f"💰 {pct} % ispod medijana traženih {basis}"
        if diff >= PRICEY:
            return f"💸 {pct} % iznad medijana traženih {basis}"
        return f"📊 oko medijana traženih {basis}"
