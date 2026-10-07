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


def layer_names(xml: str, tag: str) -> list[tuple[str, str]]:
    """(Name, Title) slojeva iz GetCapabilities (WMS Layer ili WFS FeatureType)."""
    out = []
    for block in re.findall(rf"<(?:\w+:)?{tag}\b[^>]*>(.*?)</(?:\w+:)?{tag}>", xml, re.S):
        name = re.search(r"<(?:\w+:)?Name>([^<]+)</", block)
        title = re.search(r"<(?:\w+:)?Title>([^<]*)</", block)
        if name:
            out.append((name.group(1).strip(), (title.group(1).strip() if title else "")))
    return out


def main(out: Path) -> None:
    """Sedmi krug: GetMap u vektorskom obliku (KML s atributima, JSON, SVG, MVT) preko
    posrednika – svi blokovi u pravokutniku; usporedba s GetFeatureInfo na manjim kvadratima."""
    out.mkdir(parents=True, exist_ok=True)
    result: dict = {"pokusaji": []}
    ispu = Ispu()
    s = ispu.session
    s.get(SITE, timeout=60)
    x, y = to_htrs(45.0270, 14.5752)             # Krk
    x0, y0 = (x // 4000) * 4000, (y // 4000) * 4000    # poravnati kvadrat kao u ppv_preuzmi
    box = f"{x0:.0f},{y0:.0f},{x0 + 4000:.0f},{y0 + 4000:.0f}"
    base = {"layerHash": "xM5m5ElZUrM", "serviceId": "9", "SERVICE": "WMS", "VERSION": "1.1.1", "REQUEST": "GetMap",
            "LAYERS": "404", "STYLES": "", "SRS": "EPSG:3765", "BBOX": box, "WIDTH": 1024, "HEIGHT": 1024}
    for fmt, extra in (("application/vnd.google-earth.kml+xml", {"FORMAT_OPTIONS": "kmscore:100;kmattr:true;mode:download"}),
                       ("application/vnd.google-earth.kml xml", {"FORMAT_OPTIONS": "kmscore:100;kmattr:true"}),
                       ("kml", {"FORMAT_OPTIONS": "kmscore:100;kmattr:true"}),
                       ("application/json", {}), ("application/vnd.mapbox-vector-tile", {}), ("image/svg+xml", {}),
                       ("application/rss+xml", {}), ("application/atom+xml", {}), ("text/html; subtype=openlayers", {})):
        p = {"format": fmt}
        try:
            r = s.get(API + "gis/wms", params={**base, "FORMAT": fmt, **extra}, timeout=180)
            text = r.text if "image/png" not in (r.headers.get("content-type") or "") else ""
            p.update(status=r.status_code, vrsta=r.headers.get("content-type"), duljina=len(r.content),
                     krk_gradjevinsko=text.count("KRK - GRAĐEVINSKO"), placemark=text.count("<Placemark"),
                     odgovor=text[:1500])
            if r.status_code == 200 and len(r.content) > 2000 and fmt.startswith(("application/vnd.google", "kml", "application/json", "image/svg")):
                (out / f"getmap_{re.sub(r'[^a-z]+', '_', fmt)}.txt").write_bytes(r.content[:3_000_000])
        except Exception as exc:  # noqa: BLE001
            p["greska"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        result["pokusaji"].append(p)
        print(fmt, p.get("status"), p.get("vrsta"), p.get("duljina"), p.get("placemark"), p.get("krk_gradjevinsko"))
        time.sleep(1)
    # GetFeatureInfo 1x1 na poravnatom kvadratu i na devet manjih.
    gfi = {"layerHash": "xM5m5ElZUrM", "serviceId": "9", "SERVICE": "WMS", "VERSION": "1.1.1",
           "REQUEST": "GetFeatureInfo", "LAYERS": "404", "QUERY_LAYERS": "Cjenovni_blok_PPV_2025", "STYLES": "",
           "SRS": "EPSG:3765", "WIDTH": 1, "HEIGHT": 1, "X": 0, "Y": 0, "INFO_FORMAT": "application/json",
           "FEATURE_COUNT": 1000}
    for step in (4000, 2000, 1000):
        names = set()
        for i in range(0, 4000, step):
            for j in range(0, 4000, step):
                b = f"{x0 + i:.0f},{y0 + j:.0f},{x0 + i + step:.0f},{y0 + j + step:.0f}"
                for buf in (0, 2):
                    r = s.get(API + "gis/wms", params={**gfi, "BBOX": b, "BUFFER": buf}, timeout=120)
                    if r.status_code == 200 and "json" in (r.headers.get("content-type") or ""):
                        names |= {(f.get("properties") or {}).get("cb_naziv", "") for f in r.json().get("features") or []}
                    time.sleep(0.4)
        result["pokusaji"].append({"gfi_korak": step, "blokova": len(names), "krk": sorted(n for n in names if n.startswith("KRK"))})
        print("GFI", step, len(names), sorted(n for n in names if n.startswith("KRK")))
    (out / "ppv_istrazi7.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
