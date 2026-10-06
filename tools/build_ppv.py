"""Sažima rezultat tools/ppv_preuzmi.py u data/ppv_naselja.json (Plan približnih
vrijednosti po naseljima i gradovima/općinama).

  python tools/build_ppv.py ppv-out/naselja_ppv.json.gz

Po naselju: raspon vrijednosti građevinskog zemljišta stambene i mješovite namjene
(€/m²) i vrijednosti stanova po veličini, iz cjenovnih blokova građevinskog
područja oko središta naselja. Blokovi šuma, hotela i sl. uzimaju se samo ako oko
naselja nema građevinskog bloka."""

import gzip
import json
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.text import fold  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "ppv_naselja.json"
LAND, FLATS, YEAR = "382", "383", "2026"   # slojevi PPV-a 1.1.2026. (stari oblik ulazne datoteke)
# Namjena uzor-čestice: stambena, mješovita, građevinsko područje naselja.
RESIDENTIAL = re.compile(r"^(GP|S\d?$|S-|M\d?$|M-)")
FLAT_SIZES = {"55,01 – 75,00 m2": "55-75", "75,01 – 100,00 m2": "75-100", "od 100,01 m2": "100+"}


def land_values(polja: list) -> tuple[str, str, list[float]]:
    block = use = ""
    values, cur = [], {}
    for label, value in polja:
        if label == "Naziv cjenovnog bloka":
            block = value
        elif label == "Pretežita namjena":
            use = value
        elif label == "Vrsta zemljišta":
            cur = {"vrsta": value}
        elif label == "Namjena zemljišta":
            cur["namjena"] = value
        elif label.startswith("Približne vrijednosti zemljišta") and value:
            if cur.get("vrsta", "").startswith("Građevinsko") and RESIDENTIAL.search(cur.get("namjena", "")):
                values.append(float(value))
    return block, use, values


def flat_values(polja: list) -> tuple[str, str, dict]:
    block = use = ""
    out = {}
    for label, value in polja:
        if label == "Naziv cjenovnog bloka":
            block = value
        elif label == "Opis namjene":
            use = value
        else:
            m = re.match(r"Kategorija stana/apartmana (.*) \(EUR/m2\)", label)
            if m and value and m.group(1) in FLAT_SIZES:
                out[FLAT_SIZES[m.group(1)]] = float(value)
    return block, use, out


def building(block: str, use: str) -> bool:
    return "GRAĐEVINSK" in block.upper() or "GRAĐEVINSKOG PODRUČJA" in use.upper() or "STAMBEN" in use.upper()


def summarize(row: dict, land_id: str = LAND, flats_id: str = FLATS) -> dict | None:
    land, flats = {}, {}
    for point in row.get("tocke") or []:
        for layer in point.get("slojevi") or []:
            if layer["sloj"] == land_id:
                block, use, values = land_values(layer["polja"])
                if values:
                    land[block] = (building(block, use), values)
            elif layer["sloj"] == flats_id:
                block, use, values = flat_values(layer["polja"])
                if values:
                    flats[block] = (building(block, use), values)

    def best(found: dict) -> dict:
        good = {b: v for b, (ok, v) in found.items() if ok}
        return good or {b: v for b, (_, v) in found.items()}

    out = {}
    land = best(land)
    if land:
        allv = [v for vs in land.values() for v in vs]
        out["zemljiste"] = [round(min(allv)), round(max(allv))]
    flats = best(flats)
    if flats:
        out["stanovi"] = {size: round(statistics.median(v[size] for v in flats.values() if size in v))
                          for size in FLAT_SIZES.values() if any(size in v for v in flats.values())}
    if not out:
        return None
    out["blokovi"] = sorted(set(land) | set(flats))
    return out


def build(rows: list[dict], land_id: str = LAND, flats_id: str = FLATS, year: str = YEAR) -> dict:
    naselja: dict[str, dict] = {}
    for row in rows:
        item = summarize(row, land_id, flats_id)
        if item:
            naselja.setdefault(row["jls"], {})[fold(row["naselje"])] = item
    # Grad/općina (za oglase bez prepoznatog naselja): zemljište kao raspon svih naselja
    # (medijan bi zavarao: npr. Krk – sela oko 75 €/m², grad 191–290 €/m²), stanovi kao
    # medijan naselja.
    jls = {}
    for name, places in naselja.items():
        lows = [p["zemljiste"][0] for p in places.values() if "zemljiste" in p]
        highs = [p["zemljiste"][1] for p in places.values() if "zemljiste" in p]
        item = {"naselja": len(places)}
        if lows:
            item["zemljiste"] = [min(lows), max(highs)]
        flats = {}
        for size in FLAT_SIZES.values():
            vals = [p["stanovi"][size] for p in places.values() if size in p.get("stanovi", {})]
            if vals:
                flats[size] = round(statistics.median(vals))
        if flats:
            item["stanovi"] = flats
        jls[name] = item
    return {"izvor": f"ISPU, Plan približnih vrijednosti 1.1.{year}.", "godina": int(year), "gradovi_opcine": jls,
            "naselja": naselja}


def main():
    raw = json.loads(gzip.decompress(Path(sys.argv[1]).read_bytes()))
    if isinstance(raw, dict):                 # tools/ppv_preuzmi.py: slojevi i godina uz naselja
        layers = raw["slojevi"]
        data = build(raw["naselja"], str(layers["zemljista"]), str(layers["stanovi"]), str(layers["godina"]))
    else:
        data = build(raw)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    n = sum(len(v) for v in data["naselja"].values())
    print(f"{OUT}: {n} naselja, {len(data['gradovi_opcine'])} gradova/općina")


if __name__ == "__main__":
    main()
