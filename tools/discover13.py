"""Trinaesti krug: Plan približnih vrijednosti (ISPU) za točku – poziv koji koristi
sama stranica (POST api/v1/gis/identify). Ako radi, vrijednosti za sva naselja 15
gradova/općina (središte naselja iz GeoNamesa): zemljišta i stanovi, PPV 1.1.2026."""

import gzip
import json
import sys
import time
import traceback
from pathlib import Path

from curl_cffi import requests as cffi
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from discover10 import settlements  # noqa: E402
from scraper.locations import Locator  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "debug-out") / "discovery13"
DEADLINE = time.monotonic() + 18 * 60
API = "https://ispu.mgipu.hr/api/v1/"
TO_HTRS = Transformer.from_crs("EPSG:4326", "EPSG:3765", always_xy=True)
POINTS = {"krk_centar": (45.0272, 14.5753), "njivice": (45.1655, 14.5480), "crikvenica": (45.1767, 14.6926),
          "rijeka_zamet": (45.3420, 14.3990), "brzac": (45.0875, 14.5900)}
WANTED = {"ppv_zemljista": "PPV 1.1.2026. – zemljišta", "ppv_stanovi": "PPV 1.1.2026. – stanovi/apartmani",
          "cjenovni_blokovi": "Cjenovni blokovi", "gradjevinska_podrucja": "Građevinska područja"}


def save(name, data):
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=1) if not isinstance(data, str) else data
    path.write_bytes(gzip.compress(text.encode("utf-8")) if name.endswith(".gz") else text.encode("utf-8"))


def catalog_layers(session) -> dict:
    """Slojevi iz kataloga, u obliku koji stranica šalje u identify."""
    tree = session.get(API + "gis/catalog-izbornik", timeout=60).json()
    found = {}

    def walk(o):
        if isinstance(o, dict):
            label = o.get("label") if isinstance(o.get("label"), dict) else None
            if label and o.get("type") == "sloj":
                for key, want in WANTED.items():
                    if key not in found and label.get("hr", "").startswith(want):
                        ext = o.get("extensionData") or {}
                        found[key] = {"id": o["id"], "hashIdentify": (o.get("info") or {}).get("hashIdentify"),
                                      "serviceId": ext.get("serviceId"), "layers": (ext.get("params") or {}).get("layers"),
                                      "hash": ext.get("layerHash"), "label": label, "_scales": ext.get("scales")}
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(tree)
    return found


def identify(session, lat, lon, layers: list[dict], scale=5000) -> dict:
    x, y = TO_HTRS.transform(lon, lat)
    body = {"x": x, "y": y, "scale": scale, "layers": [{k: v for k, v in la.items() if not k.startswith("_")} for la in layers]}
    r = session.post(API + "gis/identify", json=body, timeout=60,
                     headers={"Accept": "application/json", "Content-Type": "application/json",
                              "Origin": "https://ispu.mgipu.hr", "Referer": "https://ispu.mgipu.hr/"})
    try:
        data = r.json()
    except ValueError:
        data = r.text[:3000]
    return {"status": r.status_code, "data": data}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {"started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        session = cffi.Session(impersonate="chrome")
        session.get("https://ispu.mgipu.hr/", timeout=60)
        session.get(API + "auth/authz", timeout=60)
        layers = catalog_layers(session)
        summary["layers"] = layers
        tests = {}
        for name, (lat, lon) in POINTS.items():
            for key, layer in layers.items():
                for scale in (2000, 5000):
                    tests[f"{name}:{key}:{scale}"] = identify(session, lat, lon, [layer], scale)
                    time.sleep(0.7)
            save("probe.json", tests)
        ok = {k: v for k, v in tests.items() if v["status"] == 200 and v["data"] and "PPV" in json.dumps(v["data"], ensure_ascii=False)}
        summary["probe_ok"] = len(ok)
        summary["probe_sample"] = {k: json.dumps(v, ensure_ascii=False)[:2500] for k, v in list(tests.items())[:8]}
        if ok or any(v["status"] == 200 for v in tests.values()):
            rows, missing = settlements(Locator())
            summary["settlements"] = len(rows)
            summary["missing_settlements"] = missing[:80]
            out = []
            for row in rows:
                if time.monotonic() > DEADLINE:
                    summary["stopped"] = f"vrijeme, {len(out)} naselja"
                    break
                item = dict(row)
                for key in ("ppv_zemljista", "ppv_stanovi"):
                    if key in layers:
                        item[key] = identify(session, row["lat"], row["lon"], [layers[key]], 2000)
                        time.sleep(0.5)
                out.append(item)
                if len(out) % 20 == 0:
                    save("naselja_ppv.json.gz", out)
            save("naselja_ppv.json.gz", out)
            summary["done"] = len(out)
    except Exception:  # noqa: BLE001
        summary["error"] = traceback.format_exc()[-3000:]
    finally:
        summary["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        save("sazetak.json", summary)


if __name__ == "__main__":
    main()
