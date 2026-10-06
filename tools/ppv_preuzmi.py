"""Preuzimanje Plana približnih vrijednosti (PPV, ISPU) po naseljima – jednom godišnje,
nakon što Ministarstvo objavi novi PPV (stanje 1.1.). Pokreće se na GitHubu (tijek
"PPV – godišnje osvježavanje"), a zatim tools/build_ppv.py sažme rezultat u
data/ppv_naselja.json.

Za svako naselje naših gradova/općina: središte iz GeoNamesa (kojih nema: OSM
Nominatim) i četiri točke 300 m oko njega – središte zna pasti u šumu ili hotel.
Za svaku točku ISPU identify sa slojevima najnovijeg PPV-a za zemljišta i stanove.

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
OFFSETS = [(0, 0), (300, 0), (-300, 0), (0, 300), (0, -300)]   # metri (istok, sjever)
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


def ppv_layers(session) -> tuple[str, dict, dict]:
    """(godina, sloj zemljišta, sloj stanova) najnovijeg PPV-a u katalogu ISPU-a."""
    found: list[dict] = []
    Ispu(session=session)._walk(session.get(API + "gis/catalog-izbornik", timeout=60).json(), [], found)
    by_year: dict[str, dict] = {}
    for la in found:
        m = re.match(r"PPV 1\.1\.(\d{4})\. – (zemljišta|stanovi/apartmani)", la["label"].get("hr", ""))
        if m:
            by_year.setdefault(m.group(1), {})[m.group(2)] = la
    year = max(y for y, v in by_year.items() if len(v) == 2)
    pick = by_year[year]
    clean = {k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")} for k, v in pick.items()}
    return year, clean["zemljišta"], clean["stanovi/apartmani"]


def parse(data) -> list[dict]:
    """Odgovor identify → po sloju: oznake i vrijednosti (kao u ISPU-u)."""
    out = []
    for layer in data if isinstance(data, list) else (data or {}).get("data") or []:
        for item in layer.get("items") or []:
            out.append({"sloj": layer.get("catalogId"),
                        "polja": [[x["label"]["hr"], x["value"]] for x in item.get("items") or []]})
    return out


def main():
    out_path = Path(sys.argv[1] if len(sys.argv) > 1 else "ppv-out/naselja_ppv.json.gz")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    result = {"slojevi": {}, "naselja": [], "sazetak": {}}

    def save():
        out_path.write_bytes(gzip.compress(json.dumps(result, ensure_ascii=False).encode("utf-8")))

    try:
        rows, missing = settlements(Locator())
        extra = geocode(missing)
        result["sazetak"] = {"geonames": len(rows), "nedostaje": len(missing), "nominatim": len(extra)}
        rows += extra
        session = cffi.Session(impersonate="chrome")
        session.get("https://ispu.mgipu.hr/", timeout=60)
        year, land, flats = ppv_layers(session)
        result["slojevi"] = {"godina": year, "zemljista": land["id"], "stanovi": flats["id"]}
        print(f"PPV 1.1.{year}.: slojevi {land['id']} (zemljišta), {flats['id']} (stanovi); {len(rows)} naselja", flush=True)
        for row in rows:
            if time.monotonic() > DEADLINE:
                result["sazetak"]["zaustavljeno"] = f"vrijeme, {len(result['naselja'])} od {len(rows)} naselja"
                break
            x0, y0 = to_htrs(row["lat"], row["lon"])
            row["tocke"] = []
            for dx, dy in OFFSETS:
                body = {"x": x0 + dx, "y": y0 + dy, "scale": 2000, "layers": [land, flats]}
                for attempt in range(2):     # ISPU zna vratiti prolaznu grešku kod brzih upita
                    try:
                        r = session.post(API + "gis/identify", json=body, headers=ISPU_HEADERS, timeout=60)
                        if r.status_code == 200 or attempt:
                            row["tocke"].append({"dx": dx, "dy": dy, "status": r.status_code,
                                                 "slojevi": parse(r.json()) if r.status_code == 200 else []})
                            break
                    except Exception as exc:  # noqa: BLE001
                        if attempt:
                            row["tocke"].append({"dx": dx, "dy": dy, "error": str(exc)[:200]})
                    time.sleep(1)
                time.sleep(0.3)
            result["naselja"].append(row)
            if len(result["naselja"]) % 25 == 0:
                save()
    except Exception:  # noqa: BLE001
        result["sazetak"]["greska"] = traceback.format_exc()[-3000:]
        print(result["sazetak"]["greska"], flush=True)
    save()
    print(json.dumps(result["sazetak"], ensure_ascii=False), flush=True)
    if "greska" in result["sazetak"] or not result["naselja"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
