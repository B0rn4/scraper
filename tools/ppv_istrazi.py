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


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    result: dict = {}
    ispu = Ispu()
    s = ispu.session
    try:
        html = s.get(SITE, timeout=60).text
        scripts = re.findall(r'<script[^>]+src="([^"]+)"', html)
        runtime = next((x for x in scripts if "runtime" in x), "")
        if runtime:                       # Angular: dijelovi aplikacije učitavaju se naknadno
            rt = s.get(urljoin(SITE, runtime), timeout=60).text
            result["runtime"] = rt[:8000]
            pairs = re.findall(r'(\d+|"[\w\-]+"):"([0-9a-f]{16,20})"', rt)
            scripts += [f"./{k.strip(chr(34))}.{v}.js" for k, v in pairs]
            scripts += [f"./{k.strip(chr(34))}-es2015.{v}.js" for k, v in pairs]
        result["skripte"] = scripts
        found: dict[str, int] = {}
        hosts: dict[str, int] = {}
        for src in scripts[:120]:
            try:
                js = s.get(urljoin(SITE, src), timeout=60).text
            except Exception as exc:  # noqa: BLE001
                result.setdefault("greske", []).append(f"{src}: {exc}")
                continue
            if js.lstrip().startswith("<"):
                continue                  # nepostojeći dio: stranica aplikacije umjesto skripte
            for m in URLS.finditer(js):
                found[m.group(1)] = found.get(m.group(1), 0) + 1
            for m in ANY_URL.finditer(js):
                hosts[m.group(0)[:150]] = hosts.get(m.group(0)[:150], 0) + 1
            for word in ("gis/", "getFeatureInfo", "GetFeatureInfo", "wfs", "WFS", "geoserver", "featureCount",
                         "feature_count", "FEATURE_COUNT"):
                for m in list(re.finditer(re.escape(word), js))[:12]:
                    result.setdefault("kontekst", []).append(js[max(0, m.start() - 160):m.end() + 160])
        result["adrese"] = sorted(found)
        result["url_ovi"] = sorted(hosts)
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
        for extra in ({}, {"featureCount": 100}, {"feature_count": 100}, {"maxFeatures": 100}, {"limit": 100}):
            body = {"x": x, "y": y, "scale": scale, "layers": layers, **extra}
            try:
                r = s.post(API + "gis/identify", json=body, headers=HEADERS, timeout=60)
                data = r.json() if r.status_code == 200 else r.text[:300]
                result["identify"].append({"mjerilo": scale, "dodatno": extra, "status": r.status_code,
                                           "blokovi": blocks(data) if r.status_code == 200 else data})
            except Exception as exc:  # noqa: BLE001
                result["identify"].append({"mjerilo": scale, "dodatno": extra, "greska": str(exc)[:300]})
            time.sleep(1.2)

    result["pogadjanja"] = []
    for g in GUESSES:
        try:
            r = s.get(SITE + g, timeout=60)
            result["pogadjanja"].append({"url": g, "status": r.status_code, "vrsta": r.headers.get("content-type"),
                                         "odgovor": r.text[:1500]})
        except Exception as exc:  # noqa: BLE001
            result["pogadjanja"].append({"url": g, "greska": str(exc)[:200]})
        time.sleep(0.5)

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
