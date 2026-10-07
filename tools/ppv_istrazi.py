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
    """Šesti krug: koliko blokova vrati GetFeatureInfo za isti kvadrat (Krk) ovisno o
    veličini slike i BUFFER-u – slika od 1 piksela preskače male blokove."""
    out.mkdir(parents=True, exist_ok=True)
    result: dict = {"pokusaji": []}
    ispu = Ispu()
    s = ispu.session
    s.get(SITE, timeout=60)
    x, y = to_htrs(45.0270, 14.5752)             # Krk, stara jezgra
    for half in (2000, 1000):
        box = f"{x - half:.0f},{y - half:.0f},{x + half:.0f},{y + half:.0f}"
        for size, buf in ((1, 0), (101, 50), (255, 127), (512, 256), (512, 50)):
            c = size // 2
            params = {"layerHash": "xM5m5ElZUrM", "serviceId": "9", "SERVICE": "WMS", "VERSION": "1.1.1",
                      "REQUEST": "GetFeatureInfo", "LAYERS": "404", "QUERY_LAYERS": "Cjenovni_blok_PPV_2025",
                      "STYLES": "", "SRS": "EPSG:3765", "BBOX": box, "WIDTH": size, "HEIGHT": size, "X": c, "Y": c,
                      "BUFFER": buf, "INFO_FORMAT": "application/json", "FEATURE_COUNT": 1000}
            p = {"kvadrat_m": 2 * half, "piksela": size, "buffer": buf}
            try:
                r = s.get(API + "gis/wms", params=params, timeout=120)
                p.update(status=r.status_code, vrsta=r.headers.get("content-type"))
                if r.status_code == 200 and "json" in (r.headers.get("content-type") or ""):
                    feats = r.json().get("features") or []
                    names = sorted({(f.get("properties") or {}).get("cb_naziv", "") for f in feats})
                    p.update(znacajki=len(feats), krk=[n for n in names if n.startswith("KRK")], nazivi=names)
                else:
                    p["odgovor"] = r.text[:300]
            except Exception as exc:  # noqa: BLE001
                p["greska"] = f"{type(exc).__name__}: {str(exc)[:200]}"
            result["pokusaji"].append(p)
            print(2 * half, size, buf, p.get("status"), p.get("znacajki"), len(p.get("krk") or []), str(p.get("odgovor") or "")[:100])
            time.sleep(1)
    (out / "ppv_istrazi6.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
