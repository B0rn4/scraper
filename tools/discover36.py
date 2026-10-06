"""Trideset šesti krug: zaštićena kulturna dobra (Geoportal kulturnih dobara, Ministarstvo
kulture i medija) – WMS/WFS adrese, slojevi, odgovor za točku (GetFeatureInfo) u poznatim
povijesnim jezgrama i izvan njih; slojevi kulturne baštine u ISPU katalogu; registar."""

import json
import re
import sys
import time
import traceback
from pathlib import Path
from urllib.parse import urljoin

from curl_cffi import requests as cffi

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.ispu import API, Ispu, to_htrs  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "debug-out") / "discovery36"
GEO = "https://geoportal.kulturnadobra.hr/"
START = [GEO, GEO + "geoportal.html", "https://registar.kulturnadobra.hr/",
         "https://inspire-geoportal.ec.europa.eu/srv/api/records/4fcbe012-0bdc-496a-95a2-bd6436714af6/formatters/xml",
         "https://inspire-geoportal.ec.europa.eu/srv/api/records/299cb49d-cd5f-468f-bf8b-4c1785ea9fdd/formatters/xml"]
CANDIDATES = ["geoserver/ows?service=WMS&request=GetCapabilities", "geoserver/wms?service=WMS&request=GetCapabilities",
              "geoserver/wfs?service=WFS&request=GetCapabilities", "geoserver/web/", "ows?service=WMS&request=GetCapabilities",
              "wms?service=WMS&request=GetCapabilities", "arcgis/rest/services?f=json", "server/rest/services?f=json"]
# (naziv, lat, lon): povijesne jezgre i obične lokacije za usporedbu.
POINTS = [("Krk, stara jezgra", 45.0266, 14.5755), ("Vrbnik, jezgra", 45.0756, 14.6744),
          ("Kastav, jezgra", 45.3757, 14.3487), ("Volosko", 45.3505, 14.3185), ("Opatija, centar", 45.3376, 14.3058),
          ("Lovran, stari grad", 45.2918, 14.2741), ("Bakar, jezgra", 45.3060, 14.5340), ("Omišalj, jezgra", 45.2106, 14.5520),
          ("Malinska, nova kuća", 45.1180, 14.5370), ("Kostrena, kuće", 45.3105, 14.4950), ("Dobrinj, jezgra", 45.1360, 14.6060),
          ("Trsat, gradina", 45.3315, 14.4560)]


def save(name, data):
    (OUT / name).write_text(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=1),
                            encoding="utf-8")


def get(s, url, **kw):
    r = s.get(url, timeout=40, **kw)
    return r.status_code, r.headers.get("content-type", ""), r.text


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    s = cffi.Session(impersonate="chrome")
    summary = {"start": {}, "candidates": {}, "scripts": {}, "wms": {}, "featureinfo": {}, "ispu": {}}
    found_urls = set()
    for url in START:
        try:
            code, ctype, text = get(s, url)
            urls = set(re.findall(r"""https?://[^\s"'<>)]+""", text))
            svc = sorted(u for u in urls if re.search(r"wms|wfs|ows|geoserver|arcgis|mapserver|api", u, re.I))
            found_urls.update(svc)
            scripts = re.findall(r"""<script[^>]+src=["']([^"']+)""", text)
            summary["start"][url] = {"status": code, "type": ctype, "bytes": len(text), "service_urls": svc[:60],
                                     "scripts": scripts[:30], "head": text[:1500]}
            save(re.sub(r"[^a-z0-9]+", "_", url.lower())[:80] + ".txt", text[:400000])
            for src in scripts:
                full = urljoin(url, src)
                if full in summary["scripts"] or len(summary["scripts"]) > 25:
                    continue
                try:
                    c2, _, js = get(s, full)
                    hits = sorted(set(re.findall(r"""["'`](https?://[^"'`]+|/[a-z0-9_/.-]*(?:wms|wfs|ows|geoserver|api|layers?)[^"'`]*)["'`]""",
                                                 js, re.I)))
                    summary["scripts"][full] = {"status": c2, "bytes": len(js), "hits": hits[:80],
                                                "layers": sorted(set(re.findall(r"""["']([a-z_]+:[a-zA-Z0-9_]+)["']""", js)))[:80]}
                except Exception as exc:  # noqa: BLE001
                    summary["scripts"][full] = {"error": str(exc)[:200]}
                time.sleep(0.5)
        except Exception:  # noqa: BLE001
            summary["start"][url] = {"error": traceback.format_exc()[-500:]}
        time.sleep(1)
        save("sazetak.json", summary)

    bases = {GEO} | {re.sub(r"(?i)(wms|wfs|ows)\b.*$", "", u) for u in found_urls if re.search(r"geoserver|wms|ows", u, re.I)}
    for base in sorted(bases)[:8]:
        for c in CANDIDATES:
            url = urljoin(base if base.endswith("/") else base + "/", c)
            try:
                code, ctype, text = get(s, url)
                summary["candidates"][url] = {"status": code, "type": ctype, "bytes": len(text), "head": text[:600]}
                if code == 200 and "Capabilities" in text[:3000]:
                    save("cap_" + re.sub(r"[^a-z0-9]+", "_", url.lower())[-60:] + ".xml", text[:2_000_000])
                    names = re.findall(r"<Layer[^>]*>\s*<Name>([^<]+)</Name>\s*<Title>([^<]*)</Title>", text)
                    if not names:
                        names = re.findall(r"<FeatureType[^>]*>\s*<Name>([^<]+)</Name>\s*<Title>([^<]*)</Title>", text)
                    summary["wms"][url] = names[:200]
            except Exception as exc:  # noqa: BLE001
                summary["candidates"][url] = {"error": str(exc)[:200]}
            time.sleep(0.5)
    save("sazetak.json", summary)

    # GetFeatureInfo na točkama, za svaki sloj iz WMS-a (EPSG:4326, mali okvir oko točke).
    for cap_url, names in summary["wms"].items():
        if "WMS" not in cap_url.upper():
            continue
        base = cap_url.split("?")[0]
        layers = [n for n, _ in names][:40]
        for label, lat, lon in POINTS:
            d = 0.0005
            params = {"service": "WMS", "version": "1.1.1", "request": "GetFeatureInfo", "srs": "EPSG:4326",
                      "bbox": f"{lon - d},{lat - d},{lon + d},{lat + d}", "width": 101, "height": 101, "x": 50, "y": 50,
                      "layers": ",".join(layers), "query_layers": ",".join(layers), "feature_count": 20}
            res = {}
            for fmt in ("application/json", "text/plain"):
                try:
                    r = s.get(base, params={**params, "info_format": fmt}, timeout=40)
                    res[fmt] = {"status": r.status_code, "text": r.text[:4000]}
                except Exception as exc:  # noqa: BLE001
                    res[fmt] = {"error": str(exc)[:200]}
            summary["featureinfo"][f"{cap_url} | {label}"] = res
            time.sleep(0.5)
    save("sazetak.json", summary)

    # ISPU: slojevi u katalogu koji se tiču kulturne baštine / zaštite.
    try:
        ispu = Ispu()
        found = []
        ispu._walk(ispu.session.get(API + "gis/catalog-izbornik", timeout=40).json(), [], found)
        heritage = [la for la in found if re.search(r"kultur|baštin|spomen|zaštit|konzerv", la["_path"] + la["label"].get("hr", ""), re.I)]
        summary["ispu"]["paths"] = sorted({la["_path"].split(" > ")[0] for la in found})
        summary["ispu"]["heritage"] = [{k: la[k] for k in ("id", "hashIdentify", "serviceId", "layers", "_path")} | {"label": la["label"].get("hr")}
                                       for la in heritage][:80]
        summary["ispu"]["identify"] = {}
        layers = [la for la in heritage if la["hashIdentify"]][:20]
        for label, lat, lon in POINTS[:6] + POINTS[8:10]:
            x, y = to_htrs(lat, lon)
            body = {"x": x, "y": y, "scale": 2000,
                    "layers": [{k: v for k, v in la.items() if not k.startswith("_")} for la in layers]}
            try:
                r = ispu.session.post(API + "gis/identify", json=body, headers={"Accept": "application/json",
                                      "Content-Type": "application/json", "Origin": "https://ispu.mgipu.hr",
                                      "Referer": "https://ispu.mgipu.hr/"}, timeout=40)
                summary["ispu"]["identify"][label] = r.text[:4000]
            except Exception as exc:  # noqa: BLE001
                summary["ispu"]["identify"][label] = str(exc)[:200]
            time.sleep(0.5)
    except Exception:  # noqa: BLE001
        summary["ispu"]["error"] = traceback.format_exc()[-800:]
    save("sazetak.json", summary)


if __name__ == "__main__":
    main()
