"""Dvanaesti krug: (1) index.hr oglas (api/aditem/single-ad) bez preglednika, polja za
parking i papire na više oglasa; (2) kako ISPU vraća vrijednost Plana približnih
vrijednosti za točku (GetFeatureInfo kroz ISPU posrednika, "identify" iz skripti)."""

import gzip
import json
import re
import sys
import time
import traceback
from pathlib import Path
from urllib.parse import urlencode

from curl_cffi import requests as cffi
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.http import Http  # noqa: E402
from scraper.locations import Locator  # noqa: E402
from scraper.runner import load_config  # noqa: E402
from scraper.sources.index_oglasi import BASE, JSON_HEADERS, IndexOglasi  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "debug-out") / "discovery12"
DEADLINE = time.monotonic() + 18 * 60
ISPU = "https://ispu.mgipu.hr"
TO_HTRS = Transformer.from_crs("EPSG:4326", "EPSG:3765", always_xy=True)
POINTS = {"krk_centar": (45.0272, 14.5753), "malinska": (45.1245, 14.5277), "njivice": (45.1655, 14.5480),
          "crikvenica": (45.1767, 14.6926), "rijeka_zamet": (45.3420, 14.3990), "opatija": (45.3377, 14.3058)}
# Slojevi iz ISPU kataloga (catalog-izbornik): (sloj, layerHash, hashIdentify, servis)
LAYERS = {
    "ppv2026_zemljista": ("404", "xM5m5ElZUrM", "mDTOMEBYawA", "9"),
    "ppv2026_stanovi": ("405", "2WjyykEE2c", "MD5R4JU0Ew", "9"),
    "cjenovni_blokovi": ("222", "C4wheP5ELdY", "zgbURFuM4", "9"),
}
PARKING = ("garage", "garageSpace", "onSiteParking", "enclosedCarPark", "noEnclosedCarPark", "freePublicParking",
           "chargeablePublicParking", "ownershipCertificate", "buildingPermit", "usePermit", "houseType", "landType",
           "landUse", "yearBuilt", "structuralRemodelYear", "gardenArea", "latitude", "longitude", "isPreciseLocation",
           "settlementLatitude", "settlementLongitude", "averagePriceM2", "lowerRangePriceM2", "higherRangePriceM2",
           "newBuild", "asphaltRoad", "numberOfFloors")


def save(name, data):
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, (dict, list)):
        data = json.dumps(data, ensure_ascii=False, indent=1)
    if isinstance(data, str):
        data = data.encode("utf-8")
    path.write_bytes(gzip.compress(data) if name.endswith(".gz") else data)


# ---------------------------------------------------------------- index.hr

def index_single(summary):
    cfg = load_config()
    http = Http(delay=1.5)
    src = IndexOglasi(http, Locator(), cfg["kriteriji"])
    out = {"fields": {}, "samples": []}
    counts: dict[str, int] = {}
    for category in ("houses-for-sale", "lands-for-sale"):
        items = (src._api(category, 1).get("data") or [])[:8]
        for x in items:
            code = x.get("code")
            r = http.get(f"{BASE}/api/aditem/single-ad?code={code}&format=1", headers=JSON_HEADERS)
            data = r.json()
            ad = (data.get("data") or [{}])[0]
            for k, v in ad.items():
                if v not in (None, "", [], False):
                    counts[f"{category}:{k}"] = counts.get(f"{category}:{k}", 0) + 1
            out["samples"].append({"category": category, "code": code, "status": r.status_code,
                                   "description_len": len(ad.get("description") or ""),
                                   **{k: ad.get(k) for k in PARKING if k in ad}})
            if len(out["samples"]) <= 2:
                save(f"index/single_{code}.json", data)
    out["fields"] = dict(sorted(counts.items()))
    summary["index_single"] = out


# ---------------------------------------------------------------- ISPU

def ispu_js(session, summary):
    """Skripte ISPU-a: kako se zove "identify" (vrijednost sloja za točku)."""
    html = session.get(f"{ISPU}/", timeout=40).text
    names = set(re.findall(r'src="\./([\w.]+\.js)"', html))
    runtime = next((n for n in names if n.startswith("runtime")), None)
    if runtime:
        body = session.get(f"{ISPU}/{runtime}", timeout=40).text
        # Webpack: {374:"dfb7…",…}[e] → 374.dfb7….js
        for num, h in re.findall(r'(\d+):"([0-9a-f]{16,24})"', body):
            names.add(f"{num}.{h}.js")
    hits, api_paths = [], set()
    for name in sorted(names):
        if time.monotonic() > DEADLINE:
            break
        try:
            body = session.get(f"{ISPU}/{name}", timeout=60).text
        except Exception:  # noqa: BLE001
            continue
        api_paths |= set(re.findall(r'["\'`](/?api/v1/[\w\-/]+)', body))
        api_paths |= set(re.findall(r'["\'`](gis/[\w\-/]+)["\'`]', body))
        for m in re.finditer(r"(?i)identify|GetFeatureInfo|featureinfo|hashIdentify", body):
            hits.append({"js": name, "ctx": body[max(0, m.start() - 300): m.start() + 400]})
            if len(hits) > 400:
                break
    save("ispu/js_identify.json", hits)
    summary["ispu_js_files"] = sorted(names)
    summary["ispu_api_paths"] = sorted(api_paths)
    summary["ispu_identify_hits"] = len(hits)


def ispu_feature_info(session, summary):
    results = {}
    for lname, (layer, lhash, ihash, svc) in LAYERS.items():
        cap = session.get(f"{ISPU}/api/v1/gis/get-capabilities-servis?{urlencode({'servisId': svc, 'layers': layer, 'layerHash': lhash})}",
                          timeout=60)
        save(f"ispu/caps_{lname}.xml", cap.text)
        results[f"{lname}:caps"] = {"status": cap.status_code, "bytes": len(cap.text),
                                     "formats": re.findall(r"<Format>([^<]*(?:json|html|plain|gml|xml)[^<]*)</Format>", cap.text)[:12]}
        lat, lon = POINTS["krk_centar"] if "zemlj" in lname else POINTS["rijeka_zamet"]
        x, y = TO_HTRS.transform(lon, lat)
        d = 25.0
        for hash_name, h in (("layerHash", lhash), ("hashIdentify", ihash)):
            for fmt in ("application/json", "text/html", "text/plain", "application/vnd.ogc.gml"):
                if time.monotonic() > DEADLINE:
                    break
                params = {"SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetFeatureInfo", "LAYERS": layer,
                          "QUERY_LAYERS": layer, "layerHash": h, "serviceId": svc, "CRS": "EPSG:3765", "STYLES": "",
                          "BBOX": f"{x - d},{y - d},{x + d},{y + d}", "WIDTH": 101, "HEIGHT": 101, "I": 50, "J": 50,
                          "INFO_FORMAT": fmt, "FEATURE_COUNT": 5}
                try:
                    r = session.get(f"{ISPU}/api/v1/gis/wms?{urlencode(params)}", timeout=40)
                    results[f"{lname}:{hash_name}:{fmt}"] = {"status": r.status_code, "ctype": r.headers.get("content-type", ""),
                                                             "body": r.text[:1500]}
                except Exception as exc:  # noqa: BLE001
                    results[f"{lname}:{hash_name}:{fmt}"] = {"error": str(exc)[:200]}
    summary["ispu_feature_info"] = results


def ispu_browser(summary):
    """Pravi preglednik: uključi PPV zemljišta u stablu slojeva, klikni na kartu (Krk) i
    zabilježi zahtjev koji stranica šalje za vrijednost na točki."""
    from playwright.sync_api import sync_playwright
    log = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(locale="hr-HR", viewport={"width": 1500, "height": 950})

        def on_response(resp):
            req = resp.request
            if req.resource_type in ("xhr", "fetch") and "ispu" in resp.url and "GetMap" not in resp.url:
                entry = {"method": req.method, "url": resp.url[:800], "status": resp.status, "post": (req.post_data or "")[:1500]}
                try:
                    entry["body"] = resp.text()[:3000]
                except Exception:  # noqa: BLE001
                    pass
                log.append(entry)

        page.on("response", on_response)
        steps = []
        try:
            page.goto(f"{ISPU}/", wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(8000)
            for label in ("Slojevi iz nadležnosti Ministarstva (MPGI)", "Plan približnih vrijednosti", "Zemljišta",
                          "PPV 1.1.2026. – zemljišta"):
                try:
                    el = page.get_by_text(label, exact=True).first
                    el.scroll_into_view_if_needed(timeout=5000)
                    el.click(timeout=5000)
                    page.wait_for_timeout(2500)
                    steps.append(f"klik: {label}")
                except Exception as exc:  # noqa: BLE001
                    steps.append(f"{label}: {type(exc).__name__}")
            page.screenshot(path=str(OUT / "ispu" / "stablo.png"))
            # Karta je u sredini zaslona; klikovi na nekoliko mjesta.
            for xy in ((900, 450), (950, 500), (850, 520)):
                page.mouse.click(*xy)
                page.wait_for_timeout(4000)
            page.screenshot(path=str(OUT / "ispu" / "klik.png"))
        except Exception as exc:  # noqa: BLE001
            steps.append(f"greška: {type(exc).__name__}: {str(exc)[:200]}")
        browser.close()
    summary["ispu_browser_steps"] = steps
    save("ispu/browser_requests.json", log)
    summary["ispu_browser_api"] = [f"{e['method']} {e['status']} {e['url'][:300]}" for e in log][:80]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "ispu").mkdir(exist_ok=True)
    summary = {"started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    session = cffi.Session(impersonate="chrome")
    for name, step in (("index", lambda: index_single(summary)),
                       ("ispu_js", lambda: ispu_js(session, summary)),
                       ("ispu_fi", lambda: ispu_feature_info(session, summary)),
                       ("ispu_browser", lambda: ispu_browser(summary))):
        if time.monotonic() > DEADLINE:
            summary[f"{name}_skipped"] = "vrijeme"
            continue
        try:
            step()
        except Exception:  # noqa: BLE001
            summary[f"{name}_error"] = traceback.format_exc()[-2000:]
        finally:
            save("sazetak.json", summary)
    summary["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    save("sazetak.json", summary)


if __name__ == "__main__":
    main()
