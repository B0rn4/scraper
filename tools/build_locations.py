"""Generira data/locations.yaml iz popisa lokacija index.hr (PGŽ).

Izvor: data/sources/index_locations_pgz.json (županija → grad/općina → naselje,
za Rijeku kvartovi). Index.hr ima nekoliko odstupanja od službene podjele pa se
ovdje ispravljaju: "Opatija - Okolica" pripada Gradu Opatiji, Lopar je zasebna
općina (index ga drži pod Rabom), "Bakar-dio" je naselje Bakar.

Pokretanje: python tools/build_locations.py
"""

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "sources" / "index_locations_pgz.json"
DST = ROOT / "data" / "locations.yaml"

GRADOVI = {
    "Bakar", "Cres", "Crikvenica", "Čabar", "Delnice", "Kastav", "Kraljevica", "Krk",
    "Mali Lošinj", "Novi Vinodolski", "Opatija", "Rab", "Rijeka", "Vrbovsko",
}
MERGE_CITY = {"Opatija - Okolica": "Opatija"}
RENAME_CITY = {"Vinodolska Općina": "Vinodolska općina"}
RENAME_SETTLEMENT = {"Opatija - Centar": "Opatija", "Bakar-dio": "Bakar"}
SPLIT = {("Rab", "Lopar"): "Lopar"}


def main() -> None:
    county = json.loads(SRC.read_text(encoding="utf-8"))
    cities: dict[str, list[str]] = {}
    for city in county["children"]:
        name = RENAME_CITY.get(city["name"], city["name"])
        name = MERGE_CITY.get(name, name)
        for s in city["children"]:
            settlement = RENAME_SETTLEMENT.get(s["name"], s["name"])
            target = SPLIT.get((name, settlement), name)
            cities.setdefault(target, [])
            if settlement not in cities[target]:
                cities[target].append(settlement)
        cities.setdefault(name, [])
    jls = [
        {"naziv": name, "vrsta": "grad" if name in GRADOVI else "općina", "naselja": sorted(settlements)}
        for name, settlements in sorted(cities.items())
    ]
    header = (
        "# GENERIRANO: tools/build_locations.py iz data/sources/index_locations_pgz.json.\n"
        "# Ne mijenjaj ručno; ručni dodaci idu u data/locations_extra.yaml.\n"
    )
    body = yaml.safe_dump({"zupanija": "Primorsko-goranska", "jls": jls}, allow_unicode=True, sort_keys=False, width=120)
    DST.write_text(header + body, encoding="utf-8")
    print(f"{len(jls)} gradova i općina → {DST}")


if __name__ == "__main__":
    main()
