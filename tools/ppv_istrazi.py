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
SCALES = [2000, 10000, 50000, 250000, 1000000]
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


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    result: dict = {}
    ispu = Ispu()
    s = ispu.session
    try:
        html = s.get(SITE, timeout=60).text
        scripts = re.findall(r'<script[^>]+src="([^"]+)"', html)
        result["skripte"] = scripts
        found: dict[str, int] = {}
        for src in scripts[:20]:
            try:
                js = s.get(urljoin(SITE, src), timeout=60).text
            except Exception as exc:  # noqa: BLE001
                result.setdefault("greske", []).append(f"{src}: {exc}")
                continue
            for m in URLS.finditer(js):
                found[m.group(1)] = found.get(m.group(1), 0) + 1
            for word in ("identify", "getFeatureInfo", "GetFeatureInfo", "wfs", "WFS", "bbox", "BBOX"):
                for m in list(re.finditer(re.escape(word), js))[:15]:
                    result.setdefault("kontekst", []).append(js[max(0, m.start() - 160):m.end() + 160])
        result["adrese"] = sorted(found)
    except Exception as exc:  # noqa: BLE001
        result["greska_js"] = f"{type(exc).__name__}: {exc}"

    catalog = s.get(API + "gis/catalog-izbornik", timeout=60).json()
    flat: list[dict] = []
    ispu._walk(catalog, [], flat)
    want = {la["id"] for la in flat if la["label"].get("hr", "") in ("Cjenovni blokovi", "PPV 1.1.2026. – zemljišta")}
    nodes: list = []
    raw_nodes(catalog, want, nodes)
    result["cvorovi"] = nodes
    layers = [{k: v for k, v in la.items() if not k.startswith("_")} for la in flat if la["id"] in want]

    x, y = to_htrs(*POINT)
    result["identify"] = []
    for scale in SCALES:
        for extra in ({}, {"tolerance": 200}, {"buffer": 500}):
            body = {"x": x, "y": y, "scale": scale, "layers": layers, **extra}
            try:
                r = s.post(API + "gis/identify", json=body, headers=HEADERS, timeout=60)
                data = r.json() if r.status_code == 200 else r.text[:300]
                result["identify"].append({"mjerilo": scale, "dodatno": extra, "status": r.status_code,
                                           "blokovi": blocks(data) if r.status_code == 200 else data})
            except Exception as exc:  # noqa: BLE001
                result["identify"].append({"mjerilo": scale, "dodatno": extra, "greska": str(exc)[:300]})
            time.sleep(1.2)

    # WMS GetFeatureInfo nad pravokutnikom ~2 x 2 km oko točke, slika 1 x 1 piksel.
    result["wms"] = []
    for url in [a for a in result.get("adrese", []) if re.search(r"wms|ows|geoserver", a, re.I)][:6]:
        full = urljoin(SITE, url)
        for layer in {str(la.get("layers")) for la in layers}:
            params = {"SERVICE": "WMS", "VERSION": "1.1.1", "REQUEST": "GetFeatureInfo", "LAYERS": layer,
                      "QUERY_LAYERS": layer, "SRS": "EPSG:3765", "BBOX": f"{x - 1000},{y - 1000},{x + 1000},{y + 1000}",
                      "WIDTH": 1, "HEIGHT": 1, "X": 0, "Y": 0, "INFO_FORMAT": "application/json", "FEATURE_COUNT": 500}
            try:
                r = s.get(full, params=params, timeout=60)
                result["wms"].append({"url": full, "sloj": layer, "status": r.status_code, "odgovor": r.text[:3000]})
            except Exception as exc:  # noqa: BLE001
                result["wms"].append({"url": full, "sloj": layer, "greska": str(exc)[:300]})
            time.sleep(1)
    (out / "ppv_istrazi.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in result.items()
                      if k != "kontekst"}, ensure_ascii=False)[:2000])


if __name__ == "__main__":
    main(Path(sys.argv[1]))
