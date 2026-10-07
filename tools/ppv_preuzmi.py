"""Preuzimanje Plana približnih vrijednosti (PPV, ISPU) po naseljima – jednom godišnje,
nakon što Ministarstvo objavi novi PPV (stanje 1.1.). Pokreće se na GitHubu (tijek
"PPV – godišnje osvježavanje"), a zatim tools/build_ppv.py sažme rezultat u
data/ppv_naselja.json.

Svi cjenovni blokovi PPV-a zemljišta oko naših naselja, ne samo blok na jednoj točki:
ISPU-ov WMS posrednik (api/v1/gis/wms) propušta GetFeatureInfo na GeoServer Ministarstva
kad je u LAYERS sloj iz kataloga (s njegovim layerHash), a u QUERY_LAYERS pravi naziv sloja
na GeoServeru (npr. Cjenovni_blok_PPV_2025 za PPV 1.1.2026.). Upit nad kvadratom od 4 km
slikom od jednog piksela (BUFFER=0) vrati sve blokove koji ga sijeku, s nazivom bloka,
gradom/općinom i vrijednostima zemljišta. Kvadrati su oni oko naselja (GeoNames, kojih
nema: OSM Nominatim) – more i šume između njih se ne traže.

  python tools/ppv_preuzmi.py izlaz/naselja_ppv.json.gz"""

import gzip
import io
import json
import math
import re
import sys
import time
import traceback
import zipfile
from pathlib import Path

import requests
from curl_cffi import requests as cffi

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.ispu import API, HEADERS as ISPU_HEADERS, Ispu, to_htrs  # noqa: E402
from scraper.locations import Locator  # noqa: E402
from scraper.text import fold  # noqa: E402

HEADERS = {"User-Agent": "scraper-nekretnina-pgz/1.0 (osobni projekt; github.com/B0rn4/scraper)"}
GEONAMES = "https://download.geonames.org/export/dump/HR.zip"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
BBOX = (44.85, 14.15, 45.50, 15.10)          # Kvarner: obala i otoci (jug, zapad, sjever, istok)
TILE = 4000                                  # stranica kvadrata (m)
AROUND = 2500                                # kvadrati na ovoj udaljenosti od središta naselja
FEATURE_COUNT = 1000
DEADLINE = time.monotonic() + 40 * 60


def _xy(lat, lon):
    return lon * 111_320 * math.cos(math.radians(45.2)), lat * 110_574


def settlements(locator) -> tuple[list[dict], list[str]]:
    """Naselja iz GeoNamesa; grad/općina prema data/locations.yaml. Naziv koji postoji u
    više gradova/općina dodjeljuje se onome čija su ostala naselja najbliža."""
    r = requests.get(GEONAMES, headers=HEADERS, timeout=120)
    r.raise_for_status()
    text = zipfile.ZipFile(io.BytesIO(r.content)).read("HR.txt").decode("utf-8")
    s, w, n, e = BBOX
    rows, ambiguous = [], []
    for line in text.splitlines():
        f = line.split("\t")
        if len(f) < 15 or f[6] != "P":
            continue
        lat, lon = float(f[4]), float(f[5])
        if not (s <= lat <= n and w <= lon <= e):
            continue
        matches = []
        for name in (f[1], f[2]):            # službeni naziv i ASCII oblik
            matches = [j for j in locator.by_settlement(name) if j.included]
            if matches:
                break
        row = {"naselje": f[1], "lat": lat, "lon": lon, "stanovnika": int(f[14] or 0) or None, "izvor": "geonames"}
        if len(matches) == 1:
            rows.append({**row, "jls": matches[0].name})
        elif matches:
            ambiguous.append((row, matches))
    centers: dict[str, list] = {}
    for r_ in rows:
        centers.setdefault(r_["jls"], []).append((r_["lat"], r_["lon"]))
    middle = {k: (sum(a for a, _ in v) / len(v), sum(b for _, b in v) / len(v)) for k, v in centers.items()}
    for row, matches in ambiguous:
        best = min(matches, key=lambda j: math.dist((row["lat"], row["lon"]), middle.get(j.name, (0, 0))))
        rows.append({**row, "jls": best.name})
    # Istoimena točka daleko od ostalih naselja istog grada/općine je drugo mjesto.
    rows = [r_ for r_ in rows if not middle.get(r_["jls"]) or
            math.dist(_xy(*middle[r_["jls"]]), _xy(r_["lat"], r_["lon"])) <= 15_000]
    best_rows: dict[tuple, dict] = {}
    for r_ in rows:                           # više točaka istog naselja: ona s najviše stanovnika
        key = (r_["jls"], fold(r_["naselje"]))
        if key not in best_rows or (r_["stanovnika"] or 0) > (best_rows[key]["stanovnika"] or 0):
            best_rows[key] = r_
    found = set(best_rows)
    missing = [f"{j.name}: {name}" for j in locator.jls.values() if j.included
               for name in j.settlements if (j.name, fold(name)) not in found]
    return list(best_rows.values()), missing


def geocode(missing: list[str]) -> list[dict]:
    rows = []
    for entry in missing:
        jls, name = entry.split(": ", 1)
        try:
            r = requests.get(NOMINATIM, params={"q": f"{name}, {jls}, Primorsko-goranska županija", "format": "json",
                                                "limit": 1, "countrycodes": "hr"}, headers=HEADERS, timeout=30)
            hits = r.json() if r.status_code == 200 else []
        except Exception:  # noqa: BLE001
            hits = []
        if hits:
            rows.append({"naselje": name, "jls": jls, "lat": float(hits[0]["lat"]), "lon": float(hits[0]["lon"]),
                         "izvor": "nominatim"})
        time.sleep(1.1)                       # pravila Nominatima: najviše 1 zahtjev u sekundi
    return rows


def ppv_layer(session) -> dict:
    """Najnoviji PPV zemljišta: sloj iz kataloga ISPU-a (layers, layerHash, servis) i pravi
    naziv na GeoServeru – najnoviji Cjenovni_blok_PPV_GGGG (vrijednosti iz godine GGGG
    vrijede od 1.1. sljedeće; provjerava se poljem ppv_datum)."""
    found: list[dict] = []
    Ispu(session=session)._walk(session.get(API + "gis/catalog-izbornik", timeout=60).json(), [], found)
    by_year = {}
    for la in found:
        m = re.match(r"PPV 1\.1\.(\d{4})\. – zemljišta", la["label"].get("hr", ""))
        if m:
            by_year[m.group(1)] = la
    year = max(by_year)
    la = by_year[year]
    caps = session.get(API + "gis/get-capabilities-servis", timeout=120,
                       params={"servisId": la["serviceId"], "layers": la["layers"], "layerHash": la["hash"]}).text
    names = re.findall(r"<Name>(Cjenovni_blok_PPV_(\d{4}))</Name>", caps)
    name = max(names, key=lambda n: n[1])[0]
    return {"godina": year, "layers": la["layers"], "hash": la["hash"], "servis": la["serviceId"], "geoserver": name}


def tiles(rows: list[dict]) -> list[tuple[int, int]]:
    out = set()
    for row in rows:
        x, y = to_htrs(row["lat"], row["lon"])
        for ix in range(int((x - AROUND) // TILE), int((x + AROUND) // TILE) + 1):
            for iy in range(int((y - AROUND) // TILE), int((y + AROUND) // TILE) + 1):
                out.add((ix, iy))
    return sorted(out)


def blocks_in(session, layer: dict, box: tuple[float, float, float, float]) -> list[dict]:
    """Svi blokovi koji sijeku pravokutnik (svojstva, bez geometrije; uz to središte)."""
    params = {"layerHash": layer["hash"], "serviceId": layer["servis"], "SERVICE": "WMS", "VERSION": "1.1.1",
              "REQUEST": "GetFeatureInfo", "LAYERS": layer["layers"], "QUERY_LAYERS": layer["geoserver"],
              "STYLES": "", "SRS": "EPSG:3765", "BBOX": ",".join(f"{v:.0f}" for v in box), "WIDTH": 1, "HEIGHT": 1,
              "X": 0, "Y": 0, "BUFFER": 0, "INFO_FORMAT": "application/json", "FEATURE_COUNT": FEATURE_COUNT}
    for attempt in range(3):              # ISPU zna vratiti prolaznu grešku kod brzih upita
        r = session.get(API + "gis/wms", params=params, headers=ISPU_HEADERS, timeout=120)
        if r.status_code == 200 and "json" in (r.headers.get("content-type") or ""):
            break
        time.sleep(2 * (attempt + 1))
    else:
        raise RuntimeError(f"GetFeatureInfo {box}: HTTP {r.status_code} {r.text[:200]}")
    out = []
    for f in r.json().get("features") or []:
        props = dict(f.get("properties") or {})
        props["_id"] = f.get("id")
        ring = ((f.get("geometry") or {}).get("coordinates") or [[]])[0]
        if ring and isinstance(ring[0], list) and isinstance(ring[0][0], (int, float)):
            props["_x"] = round(sum(p[0] for p in ring) / len(ring))
            props["_y"] = round(sum(p[1] for p in ring) / len(ring))
        out.append(props)
    return out


def collect(session, layer: dict, box: tuple[float, float, float, float], found: dict, depth: int = 0) -> int:
    """Blokovi pravokutnika u found (po id-u); kad odgovor dosegne FEATURE_COUNT, pravokutnik
    se dijeli na četiri. Vraća broj upita."""
    items = blocks_in(session, layer, box)
    time.sleep(0.5)
    if len(items) >= FEATURE_COUNT and depth < 3:
        x0, y0, x1, y1 = box
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        return 1 + sum(collect(session, layer, b, found, depth + 1)
                       for b in ((x0, y0, mx, my), (mx, y0, x1, my), (x0, my, mx, y1), (mx, my, x1, y1)))
    for item in items:
        found[item["_id"]] = item
    return 1


def main():
    out_path = Path(sys.argv[1] if len(sys.argv) > 1 else "ppv-out/naselja_ppv.json.gz")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    result = {"sloj": {}, "naselja": [], "blokovi": [], "sazetak": {}}

    def save():
        out_path.write_bytes(gzip.compress(json.dumps(result, ensure_ascii=False).encode("utf-8")))

    try:
        rows, missing = settlements(Locator())
        extra = geocode(missing)
        result["sazetak"] = {"geonames": len(rows), "nedostaje": len(missing), "nominatim": len(extra)}
        rows += extra
        result["naselja"] = rows
        session = cffi.Session(impersonate="chrome")
        session.get("https://ispu.mgipu.hr/", timeout=60)
        layer = ppv_layer(session)
        result["sloj"] = layer
        squares = tiles(rows)
        print(f"PPV 1.1.{layer['godina']}.: {layer['geoserver']}; {len(rows)} naselja, {len(squares)} kvadrata", flush=True)
        found: dict[str, dict] = {}
        requests_ = 0
        for i, (ix, iy) in enumerate(squares):
            if time.monotonic() > DEADLINE:
                result["sazetak"]["zaustavljeno"] = f"vrijeme, {i} od {len(squares)} kvadrata"
                break
            requests_ += collect(session, layer, (ix * TILE, iy * TILE, (ix + 1) * TILE, (iy + 1) * TILE), found)
            if i % 25 == 0:
                print(f"{i}/{len(squares)} kvadrata, {len(found)} blokova", flush=True)
        result["blokovi"] = list(found.values())
        dates = {b.get("ppv_datum") for b in found.values()}
        result["sazetak"].update(kvadrata=len(squares), upita=requests_, blokova=len(found), datumi=sorted(map(str, dates)))
        if f"{layer['godina']}0101" not in dates:
            result["sazetak"]["greska"] = f"sloj {layer['geoserver']} nema PPV 1.1.{layer['godina']}. (datumi: {sorted(map(str, dates))})"
    except Exception:  # noqa: BLE001
        result["sazetak"]["greska"] = traceback.format_exc()[-3000:]
        print(result["sazetak"]["greska"], flush=True)
    save()
    print(json.dumps(result["sazetak"], ensure_ascii=False), flush=True)
    # Nepotpun popis (greška ili isteklo vrijeme) ne smije prepisati postojeću tablicu.
    if "greska" in result["sazetak"] or "zaustavljeno" in result["sazetak"] or not result["blokovi"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
