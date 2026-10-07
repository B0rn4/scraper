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
    """Četvrti krug: pravi nazivi slojeva PPV-a na GeoServeru iza ISPU-ova WMS posrednika i
    GetFeatureInfo nad cijelim pravokutnikom (jedan piksel) – svi blokovi odjednom."""
    out.mkdir(parents=True, exist_ok=True)
    result: dict = {"pokusaji": []}
    ispu = Ispu()
    s = ispu.session
    s.get(SITE, timeout=60)
    caps = s.get(API + "gis/get-capabilities-servis",
                 params={"servisId": "9", "layers": "404", "layerHash": "xM5m5ElZUrM"}, timeout=120).text
    (out / "wms_9_capabilities.xml").write_text(caps, encoding="utf-8")
    names = layer_names(caps, "Layer")
    result["wms_slojevi"] = names
    for host in ("gis2", "gis1", "gis3"):
        try:
            r = s.get(f"https://{host}.mgipu.hr/srv1/RGN_MGIPU_Public/wfs",
                      params={"service": "WFS", "request": "GetCapabilities"}, timeout=120)
            if r.status_code == 200:
                (out / "wfs_public_capabilities.xml").write_text(r.text, encoding="utf-8")
                result["wfs_javni"] = layer_names(r.text, "FeatureType")
                break
        except Exception as exc:  # noqa: BLE001
            result.setdefault("greske", []).append(f"{host}: {exc}")
    want = [n for n, t in names if re.search(r"ppv|cjenov|zemlji|blok", f"{n} {t}", re.I)]
    result["kandidati"] = want
    x, y = to_htrs(*POINT)
    box = f"{x - 1500:.0f},{y - 1500:.0f},{x + 1500:.0f},{y + 1500:.0f}"
    for name in want[:8]:
        for size, xy in ((1, 0), (101, 50)):
            params = {"layerHash": "xM5m5ElZUrM", "serviceId": "9", "SERVICE": "WMS", "VERSION": "1.1.1",
                      "REQUEST": "GetFeatureInfo", "LAYERS": name, "QUERY_LAYERS": name, "STYLES": "",
                      "SRS": "EPSG:3765", "BBOX": box, "WIDTH": size, "HEIGHT": size, "X": xy, "Y": xy,
                      "INFO_FORMAT": "application/json", "FEATURE_COUNT": 500}
            p = probe(s, API + "gis/wms", params, f"GetFeatureInfo {name} {size}x{size}")
            try:
                data = json.loads(p.get("odgovor_cijeli") or s.get(API + "gis/wms", params=params, timeout=120).text)
                feats = data.get("features") or []
                p["znacajki"] = len(feats)
                p["primjer"] = [f.get("properties") for f in feats[:3]]
                p["nazivi"] = sorted({str((f.get("properties") or {}).get(k)) for f in feats
                                      for k in (f.get("properties") or {}) if re.search(r"naziv|blok|name", k, re.I)})[:80]
            except Exception as exc:  # noqa: BLE001
                p["json_greska"] = str(exc)[:200]
            result["pokusaji"].append(p)
            time.sleep(1)
    for p in result["pokusaji"]:
        print(p.get("napomena"), p.get("status"), p.get("znacajki"), str(p.get("odgovor"))[:200].replace("\n", " "))
    print("kandidati:", want)
    (out / "ppv_istrazi4.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
