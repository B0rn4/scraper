"""Četrnaesti krug: tablica Plana približnih vrijednosti (PPV 1.1.2026.) po naseljima.

Za svako naselje 15 gradova/općina: središte (GeoNames; ako ga nema, OSM Nominatim)
i četiri točke 300 m oko njega – središte zna pasti u šumu ili hotel. Za svaku točku
ISPU identify (oba sloja u jednom pozivu): cjenovni blok, namjena, vrijednosti
građevinskog zemljišta i stanova po veličini. Sažimanje radi data/ppv (lokalno)."""

import gzip
import json
import sys
import time
import traceback
from pathlib import Path

import requests
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from discover10 import HEADERS, settlements  # noqa: E402
from discover13 import API, catalog_layers  # noqa: E402
from curl_cffi import requests as cffi  # noqa: E402
from scraper.locations import Locator  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "debug-out") / "discovery14"
DEADLINE = time.monotonic() + 19 * 60
TO_HTRS = Transformer.from_crs("EPSG:4326", "EPSG:3765", always_xy=True)
OFFSETS = [(0, 0), (300, 0), (-300, 0), (0, 300), (0, -300)]   # metri (istok, sjever)
NOMINATIM = "https://nominatim.openstreetmap.org/search"


def save(name, data):
    (OUT / name).write_bytes(gzip.compress(json.dumps(data, ensure_ascii=False).encode("utf-8"))
                             if name.endswith(".gz") else json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8"))


def parse(resp: dict) -> list[dict]:
    """Odgovor identify → po sloju: blok, namjena, vrijednosti (tekstualne oznake ISPU-a)."""
    out = []
    for layer in resp.get("data") or []:
        for item in layer.get("items") or []:
            rec = {"sloj": layer.get("catalogId"), "polja": [[x["label"]["hr"], x["value"]] for x in item.get("items") or []]}
            out.append(rec)
    return out


def geocode_missing(missing: list[str]) -> list[dict]:
    rows = []
    for entry in missing:
        if time.monotonic() > DEADLINE - 12 * 60:
            break
        jls, name = entry.split(": ", 1)
        try:
            r = requests.get(NOMINATIM, params={"q": f"{name}, {jls}, Primorsko-goranska županija", "format": "json",
                                                "limit": 1, "countrycodes": "hr"}, headers=HEADERS, timeout=30)
            hits = r.json() if r.status_code == 200 else []
        except Exception:  # noqa: BLE001
            hits = []
        if hits:
            rows.append({"naselje": name, "jls": jls, "lat": float(hits[0]["lat"]), "lon": float(hits[0]["lon"]),
                         "izvor": "nominatim", "nominatim": hits[0].get("display_name", "")[:120]})
        time.sleep(1.1)   # pravila Nominatima: najviše 1 zahtjev u sekundi
    return rows


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {"started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    out = []
    try:
        rows, missing = settlements(Locator())
        for r in rows:
            r["izvor"] = "geonames"
        extra = geocode_missing(missing)
        summary.update(geonames=len(rows), missing=len(missing), nominatim=len(extra),
                       still_missing=sorted(set(missing) - {f"{r['jls']}: {r['naselje']}" for r in extra}))
        rows += extra
        session = cffi.Session(impersonate="chrome")
        session.get("https://ispu.mgipu.hr/", timeout=60)
        session.get(API + "auth/authz", timeout=60)
        layers = catalog_layers(session)
        wanted = [{k: v for k, v in layers[key].items() if not k.startswith("_")} for key in ("ppv_zemljista", "ppv_stanovi")]
        summary["layers"] = wanted
        headers = {"Accept": "application/json", "Content-Type": "application/json",
                   "Origin": "https://ispu.mgipu.hr", "Referer": "https://ispu.mgipu.hr/"}
        for row in rows:
            if time.monotonic() > DEADLINE:
                summary["stopped"] = f"vrijeme, {len(out)} od {len(rows)} naselja"
                break
            x0, y0 = TO_HTRS.transform(row["lon"], row["lat"])
            row["tocke"] = []
            for dx, dy in OFFSETS:
                try:
                    r = session.post(API + "gis/identify", json={"x": x0 + dx, "y": y0 + dy, "scale": 2000, "layers": wanted},
                                     headers=headers, timeout=60)
                    row["tocke"].append({"dx": dx, "dy": dy, "status": r.status_code,
                                         "slojevi": parse(r.json()) if r.status_code == 200 else []})
                except Exception as exc:  # noqa: BLE001
                    row["tocke"].append({"dx": dx, "dy": dy, "error": str(exc)[:200]})
                time.sleep(0.25)
            out.append(row)
            if len(out) % 25 == 0:
                save("naselja_ppv.json.gz", out)
        summary["done"] = len(out)
    except Exception:  # noqa: BLE001
        summary["error"] = traceback.format_exc()[-3000:]
    finally:
        save("naselja_ppv.json.gz", out)
        summary["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        save("sazetak.json", summary)


if __name__ == "__main__":
    main()
