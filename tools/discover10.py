"""Korak 3.2 – tablica naselja: udaljenost od mora i vrijeme vožnje (do mora, Rijeke, Zagreba).

Pokreće se na GitHubu (workflow discover.yml). Podaci:
- naselja i granice gradova/općina: OpenStreetMap (Overpass API);
- obalna crta: OpenStreetMap (natural=coastline);
- vrijeme vožnje: OSRM (router.project-osrm.org), bez prometa – stvarno je obično dulje.

Rezultat: debug-out/discovery10/naselja.json.gz (svako naselje s koordinatama i
mjerama), obala.json.gz (pojednostavljena obala za udaljenost iz koordinata oglasa)
i sazetak.json. Zahtjevi su rijetki i s razmakom (javni servisi)."""

import gzip
import json
import math
import sys
import time
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "debug-out") / "discovery10"
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
            "https://overpass.private.coffee/api/interpreter"]
OSRM = "https://router.project-osrm.org"
RIJEKA = (45.3271, 14.4422)      # Korzo
ZAGREB = (45.8131, 15.9772)      # Trg bana Jelačića
BBOX = (44.85, 14.15, 45.50, 15.10)  # Kvarner: obala i otoci (jug, zapad, sjever, istok)
HEADERS = {"User-Agent": "scraper-nekretnina-pgz/1.0 (osobni projekt; github.com/B0rn4/scraper)"}
PLACES = "city|town|village|hamlet|isolated_dwelling|suburb|neighbourhood|quarter|locality"


def overpass(query: str) -> dict:
    """Javni Overpass poslužitelji znaju biti zauzeti (504/429): pokušava redom, s pauzama."""
    error = None
    for attempt in range(6):
        url = OVERPASS[attempt % len(OVERPASS)]
        try:
            r = requests.post(url, data={"data": query}, headers=HEADERS, timeout=300)
            if r.status_code == 200:
                return r.json()
            error = f"{url}: HTTP {r.status_code}"
        except requests.RequestException as exc:
            error = f"{url}: {exc}"
        print("Overpass:", error, flush=True)
        time.sleep(20 * (attempt + 1))
    raise RuntimeError(error)


def municipalities() -> list[dict]:
    """Granice gradova/općina (admin_level 7) na području Kvarnera: id i naziv."""
    s, w, n, e = BBOX
    data = overpass(f'[out:json][timeout:120];rel["boundary"="administrative"]["admin_level"="7"]({s},{w},{n},{e});out tags;')
    return [{"id": el["id"], "name": el["tags"].get("name", "")} for el in data["elements"]]


def settlements(jls_rels: list[dict]) -> list[dict]:
    """Naselja (place=*) unutar svakog grada/općine (područje po id-ju relacije)."""
    out = []
    for rel in jls_rels:
        data = overpass(f'[out:json][timeout:120];node(area:{3600000000 + rel["id"]})["place"~"^({PLACES})$"];out body;')
        for el in data["elements"]:
            t = el.get("tags", {})
            out.append({"jls_osm": rel["name"], "naselje": t.get("name", ""), "vrsta": t.get("place"),
                        "lat": el["lat"], "lon": el["lon"], "stanovnika": t.get("population")})
        time.sleep(5)
    return out


def coastline() -> list[list[tuple[float, float]]]:
    s, w, n, e = BBOX
    data = overpass(f'[out:json][timeout:300];way["natural"="coastline"]({s},{w},{n},{e});out geom;')
    return [[(p["lat"], p["lon"]) for p in el["geometry"]] for el in data["elements"] if el.get("geometry")]


def _xy(lat, lon):
    return lon * 111_320 * math.cos(math.radians(45.2)), lat * 110_574


def nearest_coast(lat, lon, segments) -> tuple[float, tuple[float, float]]:
    px, py = _xy(lat, lon)
    best, point = float("inf"), None
    for (ax, ay, alat, alon), (bx, by, blat, blon) in segments:
        dx, dy = bx - ax, by - ay
        t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        cx, cy = ax + t * dx, ay + t * dy
        d = math.hypot(px - cx, py - cy)
        if d < best:
            best, point = d, (alat + t * (blat - alat), alon + t * (blon - alon))
    return best, point


def osrm_table(sources: list[tuple[float, float]], dest: tuple[float, float]) -> list[float | None]:
    """Minute vožnje od svakog izvora do jednog odredišta (u paketima po 80)."""
    out = []
    for i in range(0, len(sources), 80):
        chunk = sources[i:i + 80]
        coords = ";".join(f"{lon:.5f},{lat:.5f}" for lat, lon in chunk + [dest])
        r = requests.get(f"{OSRM}/table/v1/driving/{coords}",
                         params={"sources": ";".join(map(str, range(len(chunk)))), "destinations": str(len(chunk))},
                         headers=HEADERS, timeout=120)
        r.raise_for_status()
        out += [None if row[0] is None else round(row[0] / 60, 1) for row in r.json()["durations"]]
        time.sleep(2)
    return out


def osrm_route(a, b) -> float | None:
    r = requests.get(f"{OSRM}/route/v1/driving/{a[1]:.5f},{a[0]:.5f};{b[1]:.5f},{b[0]:.5f}",
                     params={"overview": "false"}, headers=HEADERS, timeout=60)
    if r.status_code != 200 or r.json().get("code") != "Ok":
        return None
    return round(r.json()["routes"][0]["duration"] / 60, 1)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {"pocetak": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        run(summary)
    except Exception as exc:  # noqa: BLE001 – sažetak se sprema i kad nešto ne uspije
        summary["greska"] = f"{type(exc).__name__}: {exc}"[:500]
        raise
    finally:
        summary["kraj"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        (OUT / "sazetak.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")


def run(summary: dict) -> None:
    extra = yaml.safe_load((ROOT / "data" / "locations_extra.yaml").read_text(encoding="utf-8"))
    included = set(extra["ukljuceno"])

    rels = municipalities()
    summary["jls_osm"] = sorted(r["name"] for r in rels)
    ours = [r for r in rels if any(r["name"] in (f"Grad {n}", f"Općina {n}", n) for n in included)]
    summary["jls_nasi"] = sorted(r["name"] for r in ours)
    rows = settlements(ours)
    summary["naselja_u_15_jls"] = len(rows)
    time.sleep(10)

    coast = coastline()
    summary["obala_dijelova"] = len(coast)
    segments = []
    for line in coast:
        pts = [(*_xy(lat, lon), lat, lon) for lat, lon in line]
        segments += list(zip(pts, pts[1:]))
    summary["obala_segmenata"] = len(segments)
    simplified = [[(round(lat, 5), round(lon, 5)) for lat, lon in line[::2] + line[-1:]] for line in coast]
    (OUT / "obala.json.gz").write_bytes(gzip.compress(json.dumps(simplified).encode()))

    for p in rows:
        d, point = nearest_coast(p["lat"], p["lon"], segments)
        p["more_m"], p["obala_lat"], p["obala_lon"] = round(d), round(point[0], 5), round(point[1], 5)

    coords = [(p["lat"], p["lon"]) for p in rows]
    for name, dest in (("rijeka_min", RIJEKA), ("zagreb_min", ZAGREB)):
        try:
            for p, minutes in zip(rows, osrm_table(coords, dest)):
                p[name] = minutes
        except Exception as exc:  # noqa: BLE001
            summary[f"greska_{name}"] = str(exc)[:300]
    for p in rows:  # do mora: ruta do najbliže točke obale (preskače se za naselja uz samo more)
        if p["more_m"] <= 300:
            p["more_min"] = 0.0
            continue
        p["more_min"] = osrm_route((p["lat"], p["lon"]), (p["obala_lat"], p["obala_lon"]))
        time.sleep(1.1)

    (OUT / "naselja.json.gz").write_bytes(gzip.compress(json.dumps(rows, ensure_ascii=False).encode()))
    summary["primjer"] = rows[:5]


if __name__ == "__main__":
    main()
