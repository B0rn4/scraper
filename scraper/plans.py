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
    od: float = 0                    # pravilo vrijedi za česticu od … do … m²
    do: float | None = None
    zona: str = ""

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
        rules = [r for r in plan.pravila if (not zone or not r.zona or r.zona == zone)]
        sized = [r for r in rules if r.fits(area)] or rules
        if not sized:
            return None
        zones = {r.zona for r in sized if r.zona}
        where = plan.plan + (f", zona {zone}" if zone and zones else ", zona nepoznata" if len(zones) > 1 else "")
        parts = []
        mins = [r.cestica for r in sized if r.cestica]
        if mins:
            parts.append(f"min. čest. {_m2(mins)}")
        kig = [r.kig for r in sized]
        kis = [r.kis for r in sized if r.kis]
        if area:
            parts.append(f"kig {_span(kig)} (tlocrt ≤ {_m2([area * k for k in kig])})")
            if kis:
                parts.append(f"kis {_span(kis)} (GBP ≤ {_m2([area * k for k in kis])})")
        else:
            parts.append(f"kig {_span(kig)}")
            if kis:
                parts.append(f"kis {_span(kis)}")
        line = f"📏 {where}: " + " · ".join(parts)
        warning = ""
        if area and mins and area < min(mins):
            warning = (f"čestica {fmt_m2(area)} manja je od najmanje za samostojeću kuću ({fmt_m2(min(mins))}, "
                       f"{plan.plan}) – provjeri")
        return line, warning
