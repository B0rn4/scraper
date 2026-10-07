"""Sažima rezultat tools/ppv_preuzmi.py u data/ppv_naselja.json (Plan približnih
vrijednosti po naseljima i gradovima/općinama).

  python tools/build_ppv.py ppv-out/naselja_ppv.json.gz

Po naselju: sve vrijednosti građevinskog zemljišta stambene i mješovite namjene (€/m²) iz
svih cjenovnih blokova koji u nazivu imaju to naselje ("NJIVICE - GRAĐEVINSKO",
"BRUSIĆI, BAJČIĆI, POLJICA - ŠUMA"): medijan, raspon i broj blokova. Blok vrijedi za grad
ili općinu iz svog polja ppv_cb_grop. Za grad/općinu (oglas bez prepoznatog naselja):
medijan i raspon svih vrijednosti njezinih naselja. Kad blok nema grad/općinu, određuje se
po nazivu naselja, a kad isti naziv postoji u više njih, po najbližem središtu naselja.
Naselje bez bloka sa svojim imenom (zaseok unutar bloka "KOSTRENA - GRAĐEVINSKO 1") dobiva
blokove u kojima leži njegovo središte ili točka 300 m od njega (opet najprije blokove
građevinskog područja)."""

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


OFFSETS = [(0, 0), (300, 0), (-300, 0), (0, 300), (0, -300)]


def inside(x: float, y: float, ring: list) -> bool:
    """Točka unutar poligona (zrake)."""
    hit = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            hit = not hit
    return hit


def _key(name: str) -> str:
    return fold(name).replace(" ", "").replace("-", "").replace(".", "")


def build(blocks: list[dict], locator: Locator, year: str, rows: list[dict] | None = None) -> dict:
    included = [j for j in locator.jls.values() if j.included]
    jls_by_key = {_key(j.name): j for j in included}
    places_of = {j.name: {_key(n): fold(n) for n in [*j.settlements, *j.extra]} for j in included}
    centers = [(to_htrs(r["lat"], r["lon"]), r["jls"]) for r in rows or [] if r.get("lat") is not None]
    blocks = [{**b, "_id": b.get("_id") or f"b{i}"} for i, b in enumerate(blocks)]
    by_id = {b["_id"]: b for b in blocks}
    # (grad/općina, naselje) → id-evi blokova, posebno blokovi građevinskog područja (True) i
    # ostali (False); ostali se uzimaju samo kad naselje nema bloka građevinskog područja.
    found: dict[tuple[str, str], dict[bool, list[str]]] = {}
    unmatched: set[str] = set()

    def owner(block: dict):
        places = block_places(block.get("cb_naziv", ""))
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

    owners = {b["_id"]: owner(b) for b in blocks if land_values(b)}
    for bid, jls in owners.items():
        if not jls:
            continue
        block = by_id[bid]
        for place in block_places(block.get("cb_naziv", "")):
            folded = places_of[jls.name].get(_key(place))
            if not folded:
                unmatched.add(f"{jls.name}: {block.get('cb_naziv')}")
                continue
            found.setdefault((jls.name, folded), {True: [], False: []})[building(block)].append(bid)

    # Naselja bez bloka sa svojim imenom: blokovi građevinskog područja oko središta.
    for row in rows or []:
        jls_name = row.get("jls")
        place = places_of.get(jls_name, {}).get(_key(row.get("naselje", "")))
        if not place or (jls_name, place) in found or row.get("lat") is None:
            continue
        x0, y0 = to_htrs(row["lat"], row["lon"])
        hits = [bid for bid, jls in owners.items() if jls and jls.name == jls_name and by_id[bid].get("_obris")
                and any(inside(x0 + dx, y0 + dy, ring) for dx, dy in OFFSETS for ring in by_id[bid]["_obris"])]
        if hits:
            found[(jls_name, place)] = {True: [b for b in hits if building(by_id[b])],
                                        False: [b for b in hits if not building(by_id[b])]}

    def summary(ids) -> dict:
        vals = [v for bid in ids for v in land_values(by_id[bid])]
        return {"zemljiste": [round(min(vals)), round(max(vals))], "medijan": round(statistics.median(vals)),
                "blokova": len(set(ids))}

    naselja: dict[str, dict] = {}
    used: dict[str, set[str]] = {}
    for (jls, place), kinds in sorted(found.items()):
        ids = kinds[True] or kinds[False]
        naselja.setdefault(jls, {})[place] = summary(ids)
        used.setdefault(jls, set()).update(ids)
    towns = {jls: {**summary(sorted(ids)), "naselja": len(naselja[jls])} for jls, ids in used.items()}
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
