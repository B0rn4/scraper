"""Sažima rezultat tools/ppv_preuzmi.py u data/ppv_naselja.json (Plan približnih
vrijednosti po naseljima i gradovima/općinama).

  python tools/build_ppv.py ppv-out/naselja_ppv.json.gz

Po naselju: sve vrijednosti građevinskog zemljišta stambene i mješovite namjene (€/m²) iz
svih cjenovnih blokova koji u nazivu imaju to naselje ("NJIVICE - GRAĐEVINSKO",
"BRUSIĆI, BAJČIĆI, POLJICA - ŠUMA"): medijan, raspon i broj blokova. Blok vrijedi za grad
ili općinu iz svog polja ppv_cb_grop. Za grad/općinu (oglas bez prepoznatog naselja):
medijan i raspon svih vrijednosti njezinih naselja. Kad blok nema grad/općinu, određuje se
po nazivu naselja, a kad isti naziv postoji u više njih, po najbližem središtu naselja."""

import gzip
import json
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.ispu import to_htrs  # noqa: E402
from scraper.locations import Locator  # noqa: E402
from scraper.text import fold  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "ppv_naselja.json"
# Namjena uzor-čestice: stambena, mješovita, građevinsko područje naselja.
RESIDENTIAL = re.compile(r"^(GP|S\d?$|S-|M\d?$|M-)")


def land_values(block: dict) -> list[float]:
    """Vrijednosti građevinskog zemljišta stambene i mješovite namjene u bloku (do 4 retka)."""
    out = []
    for i in range(1, 5):
        kind, use, value = block.get(f"ppv_vn_{i}") or "", block.get(f"ppv_nz_{i}") or "", block.get(f"ppv_pv_eu_{i}")
        if kind.startswith("Građevinsko") and RESIDENTIAL.search(use.strip()) and value:
            out.append(float(value))
    return out


def building(block: dict) -> bool:
    """Blok građevinskog područja (ne šuma, obradivo tlo, more…)."""
    use = (block.get("cb_opis_namjene") or "").upper()
    return ("GRAĐEVINSK" in (block.get("cb_naziv") or "").upper() or "GRAĐEVINSKOG PODRUČJA" in use
            or "STAMBEN" in use or bool(RESIDENTIAL.search((block.get("cb_oznaka_namjene") or "").strip())))


def block_places(name: str) -> list[str]:
    """Naselja iz naziva bloka: dio prije zadnjeg " - " (vrsta bloka), odvojena zarezom.
    "SVETI VID - MIHOLJICE - OSTALO TLO" → ["sveti vid-miholjice"]."""
    head = re.split(r"\s+[-–]\s+(?=[^-–]*$)", (name or "").strip())[0]
    return [fold(re.sub(r"\s*[-–]\s*", "-", p.strip())) for p in head.split(",") if p.strip()]


def _key(name: str) -> str:
    return fold(name).replace(" ", "").replace("-", "").replace(".", "")


def build(blocks: list[dict], locator: Locator, year: str, rows: list[dict] | None = None) -> dict:
    included = [j for j in locator.jls.values() if j.included]
    jls_by_key = {_key(j.name): j for j in included}
    places_of = {j.name: {_key(n): fold(n) for n in [*j.settlements, *j.extra]} for j in included}
    centers = [(to_htrs(r["lat"], r["lon"]), r["jls"]) for r in rows or [] if r.get("lat") is not None]
    # (grad/općina, naselje) → [vrijednosti, broj blokova] posebno za blokove građevinskog
    # područja i ostale; ostali se uzimaju samo kad naselje nema bloka građevinskog područja.
    found: dict[tuple[str, str], dict[bool, list]] = {}
    unmatched: set[str] = set()

    def owner(block: dict, places: list[str]):
        jls = jls_by_key.get(_key(block.get("ppv_cb_grop") or ""))
        if jls or block.get("ppv_cb_grop"):
            return jls                    # tuđi grad/općina: nije naš
        cands = [j for j in included if any(_key(p) in places_of[j.name] for p in places)]
        if len(cands) > 1 and "_x" in block:
            names = {j.name for j in cands}
            near = [(abs(x - block["_x"]) + abs(y - block["_y"]), name) for (x, y), name in centers if name in names]
            if near:
                return next(j for j in cands if j.name == min(near)[1])
        return cands[0] if len(cands) == 1 else None

    for block in blocks:
        vals = land_values(block)
        places = block_places(block.get("cb_naziv", ""))
        jls = owner(block, places) if vals else None
        if not jls:
            continue
        for place in places:
            folded = places_of[jls.name].get(_key(place))
            if not folded:
                unmatched.add(f"{jls.name}: {block.get('cb_naziv')}")
                continue
            slot = found.setdefault((jls.name, folded), {True: [[], 0], False: [[], 0]})[building(block)]
            slot[0].extend(vals)
            slot[1] += 1

    def summary(vals: list[float]) -> dict:
        return {"zemljiste": [round(min(vals)), round(max(vals))], "medijan": round(statistics.median(vals))}

    naselja: dict[str, dict] = {}
    values: dict[str, list[float]] = {}
    for (jls, place), kinds in sorted(found.items()):
        vals, n = kinds[True] if kinds[True][1] else kinds[False]
        naselja.setdefault(jls, {})[place] = {**summary(vals), "blokova": n}
        values.setdefault(jls, []).extend(vals)
    towns = {jls: {**summary(vals), "naselja": len(naselja[jls]),
                   "blokova": sum(p["blokova"] for p in naselja[jls].values())} for jls, vals in values.items()}
    return {"izvor": f"ISPU, Plan približnih vrijednosti 1.1.{year}. – svi cjenovni blokovi naselja",
            "godina": int(year), "gradovi_opcine": towns, "naselja": naselja,
            "bez_naselja": sorted(unmatched)}


def main():
    raw = json.loads(gzip.decompress(Path(sys.argv[1]).read_bytes()))
    data = build(raw["blokovi"], Locator(), str(raw["sloj"]["godina"]), raw.get("naselja"))
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    n = sum(len(v) for v in data["naselja"].values())
    print(f"{OUT}: {n} naselja, {len(data['gradovi_opcine'])} gradova/općina, "
          f"{len(raw['blokovi'])} blokova; bez prepoznatog naselja: {len(data['bez_naselja'])}")
    for line in data["bez_naselja"][:60]:
        print("  ", line)


if __name__ == "__main__":
    main()
