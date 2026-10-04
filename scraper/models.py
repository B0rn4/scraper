"""Zajednički oblik oglasa i odluke filtera."""

from dataclasses import asdict, dataclass, field

HOUSE = "kuca"
LAND = "zemljiste"
OTHER = "ostalo"

PASS = "prolazi"
WARN = "upozorenje"
REJECT = "odbijen"


@dataclass
class Listing:
    source: str                    # npr. "nekretnine_hr"
    source_id: str                 # ID oglasa na izvoru
    url: str
    title: str
    kind: str                      # HOUSE, LAND ili OTHER
    subtype: str = ""              # vrsta s portala, npr. "Obiteljska kuća", "dvojni objekt"
    price: float | None = None     # €
    area: float | None = None      # stambena površina kuće ili površina zemljišta, m²
    plot_area: float | None = None # okućnica kuće, m²
    county: str = ""               # županija kako je navodi izvor
    municipality: str = ""         # grad/općina kako je navodi izvor
    settlement: str = ""           # naselje kako ga navodi izvor
    location_text: str = ""        # lokacija u slobodnom tekstu (prikaz i prepoznavanje)
    description: str = ""
    image_url: str = ""
    published: str = ""
    previous_price: float | None = None
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.source}:{self.source_id}"

    @property
    def price_per_m2(self) -> float | None:
        if self.price and self.area:
            return self.price / self.area
        return None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Decision:
    status: str                         # PASS, WARN ili REJECT
    reasons: list[str] = field(default_factory=list)   # razlozi odbijanja
    warnings: list[str] = field(default_factory=list)  # ⚠ napomene
    jls: str = ""                       # prepoznata općina/grad (naziv)
    location_evidence: str = ""         # kako je lokacija prepoznata
    near_miss: bool = False             # promašen samo za dlaku (cijena ili površina)

    @property
    def notify(self) -> bool:
        return self.status in (PASS, WARN)
