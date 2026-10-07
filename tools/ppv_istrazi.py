"""Razvoj: kako iz ISPU-a dobiti sve cjenovne blokove PPV-a jednog naselja, a ne samo
blok na točki (za PPV naselja: medijan i raspon svih blokova).

    python tools/ppv_istrazi.py IZLAZ

Zapiše (ppv_istrazi.json):
- adrese i servise koje spominje JavaScript preglednika (api/v1/…, WMS/WFS, geoserver);
- cijele čvorove kataloga za slojeve cjenovnih blokova i PPV-a zemljišta;
- odgovore identify za isto mjesto na sve većim mjerilima (vraća li ISPU više blokova);
- pokušaje WMS GetFeatureInfo nad cijelim obuhvatom naselja, ako se WMS adresa nađe."""

import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.ispu import API, HEADERS, Ispu, to_htrs  # noqa: E402

SITE = "https://ispu.mgipu.hr/"
POINT = (45.1636, 14.5517)                  # Njivice, središte
SCALES = [2000, 50000, 1000000]
GUESSES = ["geoserver/wfs?service=WFS&request=GetCapabilities", "geoserver/ows?service=WFS&request=GetCapabilities",
           "geoserver/wms?service=WMS&request=GetCapabilities", "wfs?service=WFS&request=GetCapabilities",
           "api/v1/gis/services", "api/v1/gis/service/9", "api/v1/gis/wms/9", "api/v1/servisi",
           "api/v1/gis/catalog-servisi", "api/v1/gis/servisi"]
ANY_URL = re.compile(r"https?://[\w.\-]+(?:/[\w\-./{}$?=&%]*)?")
URLS = re.compile(r"""["'`]([^"'`\s]{0,80}(?:api/v1/[\w\-/{}$.]+|[Ww][Mm][SsTt][Ss]?\b[^"'`\s]{0,60}|"""
                  r"""geoserver[^"'`\s]{0,80}|/ows[^"'`\s]{0,40}|MapServer[^"'`\s]{0,40}|GetFeatureInfo[^"'`\s]{0,40}))["'`]""")


def raw_nodes(node, want: set[str], out: list):
    if isinstance(node, dict):
        if str(node.get("id")) in want and node.get("type") == "sloj":
            out.append(node)
        for v in node.values():
            raw_nodes(v, want, out)
    elif isinstance(node, list):
        for v in node:
            raw_nodes(v, want, out)


def blocks(data) -> list[str]:
    names = []
    for layer in data if isinstance(data, list) else (data or {}).get("data") or []:
        for item in layer.get("items") or []:
            for f in item.get("items") or []:
                if f["label"]["hr"] == "Naziv cjenovnog bloka":
                    names.append(f"{layer.get('catalogId')}: {f['value']}")
    return names


def wfs_nodes(node, out: list):
    if isinstance(node, dict):
        ext = node.get("extensionData") if node.get("type") == "sloj" else None
        if isinstance(ext, dict) and ext.get("type") not in (None, "wms"):
            out.append({"id": node.get("id"), "label": (node.get("label") or {}).get("hr"), "ext": ext})
        for v in node.values():
            wfs_nodes(v, out)
    elif isinstance(node, list):
        for v in node:
            wfs_nodes(v, out)


def probe(s, url, params=None, note="") -> dict:
    try:
        r = s.get(url, params=params, timeout=90)
        return {"url": url, "napomena": note, "parametri": params, "status": r.status_code,
                "vrsta": r.headers.get("content-type"), "duljina": len(r.content), "odgovor": r.text[:4000]}
    except Exception as exc:  # noqa: BLE001
        return {"url": url, "napomena": note, "parametri": params, "greska": f"{type(exc).__name__}: {str(exc)[:300]}"}


def main(out: Path) -> None:
    """Treći krug: javni WFS Ministarstva, WMS/WFS posrednik ISPU-a za PPV slojeve."""
    out.mkdir(parents=True, exist_ok=True)
    result: dict = {"pokusaji": []}
    ispu = Ispu()
    s = ispu.session
    s.get(SITE, timeout=60)
    catalog = s.get(API + "gis/catalog-izbornik", timeout=60).json()
    nodes: list = []
    wfs_nodes(catalog, nodes)
    result["ne_wms_slojevi"] = nodes[:80]
    x, y = to_htrs(*POINT)
    box = f"{x - 1500:.0f},{y - 1500:.0f},{x + 1500:.0f},{y + 1500:.0f}"
    add = result["pokusaji"].append
    for host in ("gis1", "gis2"):
        add(probe(s, f"https://{host}.mgipu.hr/srv1/RGN_MGIPU_Public/wfs",
                  {"service": "WFS", "request": "GetCapabilities"}, "javni WFS Ministarstva"))
    layers = {"404": "xM5m5ElZUrM", "222": "C4wheP5ELdY"}      # PPV 2026 zemljišta, cjenovni blokovi
    for lay, lhash in layers.items():
        base = {"layerHash": lhash, "serviceId": "9"}
        add(probe(s, API + "gis/wms", {**base, "SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap", "LAYERS": lay,
                                       "STYLES": "", "CRS": "EPSG:3765", "BBOX": box, "WIDTH": 64, "HEIGHT": 64,
                                       "FORMAT": "image/png"}, f"GetMap {lay}"))
        for size, ij in ((1, 0), (101, 50)):
            add(probe(s, API + "gis/wms", {**base, "SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetFeatureInfo",
                                           "LAYERS": lay, "QUERY_LAYERS": lay, "STYLES": "", "CRS": "EPSG:3765",
                                           "BBOX": box, "WIDTH": size, "HEIGHT": size, "I": ij, "J": ij,
                                           "INFO_FORMAT": "application/json", "FEATURE_COUNT": 300},
                      f"GetFeatureInfo {lay} {size}x{size}"))
            add(probe(s, API + "gis/wms", {**base, "SERVICE": "WMS", "VERSION": "1.1.1", "REQUEST": "GetFeatureInfo",
                                           "LAYERS": lay, "QUERY_LAYERS": lay, "STYLES": "", "SRS": "EPSG:3765",
                                           "BBOX": box, "WIDTH": size, "HEIGHT": size, "X": ij, "Y": ij,
                                           "INFO_FORMAT": "application/json", "FEATURE_COUNT": 300},
                      f"GetFeatureInfo 1.1.1 {lay} {size}x{size}"))
        for path in ("gis/wms/wfs", "gis/wfs"):
            add(probe(s, API + path, {**base, "service": "WFS", "version": "1.1.0", "request": "GetFeature",
                                      "typename": lay, "outputFormat": "application/json", "srsname": "EPSG:3765",
                                      "bbox": box + ",EPSG:3765"}, f"WFS {path} {lay}"))
        add(probe(s, API + "gis/wms", {**base, "SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetCapabilities"},
                  f"GetCapabilities {lay}"))
        time.sleep(1)
    add(probe(s, API + "gis/get-capabilities-servis", {"servisId": "9", "layers": "404", "layerHash": "xM5m5ElZUrM"},
              "get-capabilities-servis"))
    for p in result["pokusaji"]:
        print(p.get("napomena"), p.get("status"), p.get("vrsta"), p.get("duljina"), str(p.get("odgovor") or p.get("greska"))[:160].replace("\n", " "))
    (out / "ppv_istrazi3.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
