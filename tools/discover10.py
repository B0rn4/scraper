"""Korak 3.2 – tablica naselja: udaljenost od mora i vrijeme vožnje (do mora, Rijeke, Zagreba).

Pokreće se na GitHubu (workflow discover.yml). Podaci:
- naselja: GeoNames (HR.zip), grad/općina prema našem popisu naselja;
- obalna crta: OpenStreetMap (natural=coastline), spremljena u data/sources/obala_kvarner.json.gz;
- vrijeme vožnje: OSRM (router.project-osrm.org), bez prometa – stvarno je obično dulje.

Rezultat: debug-out/discovery10/naselja.json.gz (svako naselje s koordinatama i
mjerama) i sazetak.json. Zahtjevi su rijetki i s razmakom (javni servisi)."""

import gzip
import io
import json
import math
import sys
import time
import zipfile
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scraper.locations import Locator  # noqa: E402
from scraper.text import fold  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "debug-out") / "discovery10"
GEONAMES = "https://download.geonames.org/export/dump/HR.zip"
COAST = ROOT / "data" / "sources" / "obala_kvarner.json.gz"
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


def settlements(locator) -> tuple[list[dict], list[str]]:
    """Naselja iz GeoNamesa (gotova datoteka za Hrvatsku – Overpass je bio preopterećen);
    grad/općina prema našem popisu naselja (data/locations.yaml). Naziv koji postoji u
    više gradova/općina dodjeljuje se onome čija su ostala naselja najbliža."""
    r = requests.get(GEONAMES, headers=HEADERS, timeout=120)
    r.raise_for_status()
    text = zipfile.ZipFile(io.BytesIO(r.content)).read("HR.txt").decode("utf-8")
    s, w, n, e = BBOX
    rows, ambiguous, seen = [], [], set()
    for line in text.splitlines():
        f = line.split("\t")
        if len(f) < 15 or f[6] != "P":
            continue
        lat, lon = float(f[4]), float(f[5])
        if not (s <= lat <= n and w <= lon <= e):
            continue
        names = [f[1], f[2]]  # službeni naziv i ASCII oblik
        matches = []
        for name in names:
            matches = [j for j in locator.by_settlement(name) if j.included]
            if matches:
                break
        row = {"naselje": f[1], "vrsta": f[7], "lat": lat, "lon": lon, "stanovnika": int(f[14] or 0) or None}
        if len(matches) == 1:
            rows.append({**row, "jls": matches[0].name})
        elif matches:
            ambiguous.append((row, matches))
    centers = {}
    for r_ in rows:
        centers.setdefault(r_["jls"], []).append((r_["lat"], r_["lon"]))
    centers = {k: (sum(a for a, _ in v) / len(v), sum(b for _, b in v) / len(v)) for k, v in centers.items()}
    for row, matches in ambiguous:
        best = min(matches, key=lambda j: math.dist((row["lat"], row["lon"]), centers.get(j.name, (0, 0))))
        rows.append({**row, "jls": best.name, "dvoznacno": [j.name for j in matches]})
    # Istoimena točka daleko od ostalih naselja istog grada/općine je drugo mjesto.
    for r_ in list(rows):
        center = centers.get(r_["jls"])
        if center and math.dist(_xy(*center), _xy(r_["lat"], r_["lon"])) > 15_000:
            rows.remove(r_)
    # Jedno naselje može imati više točaka (npr. dio naselja); zadrži onu s najviše stanovnika.
    best_rows = {}
    for r_ in rows:
        key = (r_["jls"], fold(r_["naselje"]))
        if key not in best_rows or (r_["stanovnika"] or 0) > (best_rows[key]["stanovnika"] or 0):
            best_rows[key] = r_
    rows = list(best_rows.values())
    found = {(r_["jls"], fold(r_["naselje"])) for r_ in rows}
    missing = [f"{j.name}: {name}" for j in locator.jls.values() if j.included
               for name in j.settlements if (j.name, fold(name)) not in found]
    return rows, missing


def coastline() -> list[list[tuple[float, float]]]:
    """Obalna crta Kvarnera (OpenStreetMap natural=coastline, preuzeto 5. 10. 2026.)."""
    return json.loads(gzip.decompress(COAST.read_bytes()))


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


def osrm_nearest(sources: list[tuple[float, float]], dests: list[tuple[float, float]]) -> list[float | None]:
    """Za svaki izvor: minute vožnje do najbližeg od odredišta (naselja uz more)."""
    out = []
    for i in range(0, len(sources), 40):
        chunk = sources[i:i + 40]
        coords = ";".join(f"{lon:.5f},{lat:.5f}" for lat, lon in chunk + dests)
        r = requests.get(f"{OSRM}/table/v1/driving/{coords}",
                         params={"sources": ";".join(map(str, range(len(chunk)))),
                                 "destinations": ";".join(str(len(chunk) + j) for j in range(len(dests)))},
                         headers=HEADERS, timeout=120)
        r.raise_for_status()
        for row in r.json()["durations"]:
            values = [v for v in row if v is not None]
            out.append(round(min(values) / 60, 1) if values else None)
        time.sleep(2)
    return out


def sea_candidates(lat, lon, coast_xy, n=14, spacing=350.0, radius=8_000.0) -> list[tuple[float, float]]:
    """Najbliže točke obale, međusobno udaljene barem `spacing` m (različite uvale/plaže)."""
    px, py = _xy(lat, lon)
    near = sorted((math.hypot(x - px, y - py), x, y, la, lo) for x, y, la, lo in coast_xy
                  if abs(x - px) < radius and abs(y - py) < radius)
    chosen = []
    for d, x, y, la, lo in near:
        if d > radius:
            break
        if all(math.hypot(x - cx, y - cy) >= spacing for _, cx, cy, _, _ in chosen):
            chosen.append((d, x, y, la, lo))
            if len(chosen) >= n:
                break
    return [(la, lo) for _, _, _, la, lo in chosen]


def sea_drive(lat, lon, candidates, max_snap=300.0) -> tuple[float | None, tuple | None]:
    """Minute vožnje do mjesta gdje cesta dolazi do mora (do max_snap m od obale)."""
    if not candidates:
        return None, None
    coords = ";".join(f"{lo:.5f},{la:.5f}" for la, lo in [(lat, lon)] + candidates)
    r = requests.get(f"{OSRM}/table/v1/driving/{coords}",
                     params={"sources": "0", "destinations": ";".join(str(i + 1) for i in range(len(candidates)))},
                     headers=HEADERS, timeout=60)
    r.raise_for_status()
    data = r.json()
    best = (None, None)
    for duration, dest, cand in zip(data["durations"][0], data["destinations"], candidates):
        if duration is None or dest.get("distance", 1e9) > max_snap:
            continue
        if best[0] is None or duration < best[0]:
            best = (round(duration / 60, 1), cand)
    return best


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
    rows, missing = settlements(Locator())
    summary["naselja_u_15_jls"] = len(rows)
    summary["nema_u_geonames"] = missing
    time.sleep(10)

    coast = coastline()
    summary["obala_dijelova"] = len(coast)
    segments = []
    for line in coast:
        pts = [(*_xy(lat, lon), lat, lon) for lat, lon in line]
        segments += list(zip(pts, pts[1:]))
    summary["obala_segmenata"] = len(segments)

    for p in rows:
        d, point = nearest_coast(p["lat"], p["lon"], segments)
        p["more_m"], p["obala_lat"], p["obala_lon"] = round(d), round(point[0], 5), round(point[1], 5)

    save = lambda: (OUT / "naselja.json.gz").write_bytes(gzip.compress(json.dumps(rows, ensure_ascii=False).encode()))  # noqa: E731
    save()  # djelomični rezultat, ako vožnja ne uspije
    coords = [(p["lat"], p["lon"]) for p in rows]
    for name, dest in (("rijeka_min", RIJEKA), ("zagreb_min", ZAGREB)):
        try:
            for p, minutes in zip(rows, osrm_table(coords, dest)):
                p[name] = minutes
        except Exception as exc:  # noqa: BLE001
            summary[f"greska_{name}"] = str(exc)[:300]
    # Do mora: vožnja do najbližeg mjesta gdje cesta dolazi do obale (plaža, uvala, luka).
    # Kandidati su najbliže točke obale u različitim uvalama; vrijedi samo ako cesta
    # prolazi najviše 300 m od te točke (inače je obala stijena bez pristupa).
    coast_xy = [(*_xy(la, lo), la, lo) for line in coast for la, lo in line]
    for p in rows:
        if p["more_m"] <= 300:
            p["more_min"] = 0.0
            continue
        try:
            p["more_min"], target = sea_drive(p["lat"], p["lon"], sea_candidates(p["lat"], p["lon"], coast_xy))
            p["more_cilj"] = target
        except Exception as exc:  # noqa: BLE001
            summary["greska_more_min"] = str(exc)[:300]
        time.sleep(1.1)

    save()
    summary["primjer"] = rows[:5]


if __name__ == "__main__":
    main()
