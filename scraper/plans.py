"""Uvjeti gradnje samostojeće obiteljske kuće iz prostornih planova (data/uvjeti_gradnje.yaml):
najmanja građevna čestica, koeficijent izgrađenosti (kig) i iskoristivosti (kis).

Vrijedi UPU naselja ako postoji, inače PPU grada/općine. Vrijednosti ovise o zoni i
površini čestice: bira se pravilo za površinu iz oglasa; kad zona nije poznata, a pravila
se po zonama razlikuju, redak pokazuje raspon i to kaže. Podaci su prepisani iz planova
(izvor uz svaki), ne traže se pri svakom pokretanju."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .models import LAND, Listing
from .text import fmt_m2, fold

PLANS_FILE = Path(__file__).resolve().parent.parent / "data" / "uvjeti_gradnje.yaml"


@dataclass
class Rule:
    kig: float
    kis: float | None = None
    cestica: float | None = None     # najmanja površina građevne čestice (m²)
    iznimno: float | None = None     # manja dopuštena iznimno (postojeće čestice, interpolacija…)
    od: float = 0                    # pravilo vrijedi za česticu od … do … m²
    do: float | None = None
    zona: str = ""
    tlocrt: float | None = None      # najveća tlocrtna površina (m²), bez obzira na kig
    gbp: float | None = None         # najveća građevinska bruto površina (m²), bez obzira na kis

    def footprint(self, area: float) -> float:
        return min(area * self.kig, self.tlocrt or float("inf"))

    def floor_area(self, area: float) -> float | None:
        return min(area * self.kis, self.gbp or float("inf")) if self.kis else None

    def fits(self, area: float | None) -> bool:
        return area is None or (area >= self.od and (self.do is None or area < self.do))


@dataclass
class Plan:
    jls: str
    plan: str
    izvor: str = ""
    url: str = ""
    naselja: list[str] = field(default_factory=list)   # prazno: cijeli grad/općina (PPU)
    pravila: list[Rule] = field(default_factory=list)


def _num(value: float) -> str:
    return f"{value:g}".replace(".", ",")


def _span(values: list[float], fmt=_num) -> str:
    low, high = min(values), max(values)
    return fmt(low) if low == high else f"{fmt(low)}–{fmt(high)}"


def _m2(values: list[float]) -> str:
    return _span([round(v) for v in values], lambda v: f"{v:,.0f}".replace(",", ".")) + " m²"


class Plans:
    def __init__(self, path: Path = PLANS_FILE):
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else None
        self.plans: list[Plan] = []
        for item in data or []:
            rules = [Rule(**r) for r in item.pop("pravila", [])]
            item["naselja"] = [fold(n) for n in item.get("naselja") or []]
            self.plans.append(Plan(**item, pravila=rules))

    def find(self, jls: str, place: str) -> Plan | None:
        """UPU naselja, inače PPU grada/općine."""
        place = fold(place or "")
        local = [p for p in self.plans if p.jls == jls and place and place in p.naselja]
        whole = [p for p in self.plans if p.jls == jls and not p.naselja]
        return (local or whole or [None])[0]

    def check(self, listing: Listing, jls: str, place: str, zone: str = "") -> tuple[str, str] | None:
        """(redak za obavijest, upozorenje ili ""), samo za zemljišta."""
        if listing.kind != LAND or not jls:
            return None
        plan = self.find(jls, place)
        if not plan:
            return None
        area = listing.area or None
        if zone and not any(r.zona == zone for r in plan.pravila):
            zone = ""                    # zona s ISPU-a (izgrađeni dio…) za ovaj plan nije važna
        rules = [r for r in plan.pravila if (not zone or not r.zona or r.zona == zone)]
        sized = [r for r in rules if r.fits(area)] or rules
        if not sized:
            return None
        values = {(r.cestica, r.kig, r.kis, r.tlocrt, r.gbp) for r in sized}
        unknown = not zone and len(values) > 1 and any(r.zona for r in sized)
        where = plan.plan + (f", {zone}" if zone else ", zona nepoznata" if unknown else "")
        parts = []
        mins = [r.cestica for r in sized if r.cestica]
        if mins:
            parts.append(f"min. čest. {_m2(mins)}")
        kig = [r.kig for r in sized]
        kis = [r.kis for r in sized if r.kis]
        if area:
            parts.append(f"kig {_span(kig)} (tlocrt ≤ {_m2([r.footprint(area) for r in sized])})")
            if kis:
                parts.append(f"kis {_span(kis)} (GBP ≤ {_m2([r.floor_area(area) for r in sized if r.kis])})")
        else:
            parts.append(f"kig {_span(kig)}")
            if kis:
                parts.append(f"kis {_span(kis)}")
        line = f"📏 {where}: " + " · ".join(parts)
        warning = ""
        if area and mins and area < min(mins):
            low = [r.iznimno for r in sized if r.iznimno]
            if low and area >= min(low):
                warning = (f"čestica {fmt_m2(area)} manja je od najmanje za samostojeću kuću ({_m2(mins)}, "
                           f"{plan.plan}); iznimno je dopušteno od {_m2(low)} – provjeri")
            else:
                warning = (f"čestica {fmt_m2(area)} manja je od najmanje za samostojeću kuću ({_m2(mins)}, "
                           f"{plan.plan}) – provjeri")
        return line, warning
