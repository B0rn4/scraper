"""Petnaesti krug: ISPU – građevinska područja (sloj "Građevinska područja (rujan 2024.)")
za točku, i kako stranica traži katastarsku česticu / podatke o lokaciji
(gis/info-lokacija-*). Rezultat: slojevi, odgovori identify i isječci skripti."""

import gzip
import json
import re
import sys
import time
import traceback
from pathlib import Path

from curl_cffi import requests as cffi

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.ispu import API, HEADERS, to_htrs  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "debug-out") / "discovery15"
ISPU = "https://ispu.mgipu.hr"
POINTS = {"krk_centar": (45.0272, 14.5753), "brzac_suma": (45.0875, 14.5900), "njivice": (45.1655, 14.5480),
          "malinska_rub": (45.1180, 14.5420), "rijeka_zamet": (45.3420, 14.3990), "ucka": (45.2860, 14.2030)}


def save(name, data):
    text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=1)
    (OUT / name).write_bytes(gzip.compress(text.encode("utf-8")) if name.endswith(".gz") else text.encode("utf-8"))


def walk(node, path, out):
    if isinstance(node, dict):
        label = node.get("label") if isinstance(node.get("label"), dict) else None
        p = path + [label.get("hr", "")] if label else path
        if label and node.get("type") == "sloj":
            ext = node.get("extensionData") or {}
            out.append({"path": " > ".join(p), "id": node.get("id"), "hashIdentify": (node.get("info") or {}).get("hashIdentify"),
                        "serviceId": ext.get("serviceId"), "layers": (ext.get("params") or {}).get("layers"),
                        "hash": ext.get("layerHash"), "label": label, "scales": ext.get("scales"),
                        "identifyScales": ext.get("identifyScales")})
        for v in node.values():
            walk(v, p, out)
    elif isinstance(node, list):
        for v in node:
            walk(v, path, out)


def identify(session, lat, lon, layers, scale=2000):
    x, y = to_htrs(lat, lon)
    body = {"x": x, "y": y, "scale": scale,
            "layers": [{k: la[k] for k in ("id", "hashIdentify", "serviceId", "layers", "hash", "label")} for la in layers]}
    r = session.post(API + "gis/identify", json=body, headers=HEADERS, timeout=60)
    try:
        return {"status": r.status_code, "data": r.json()}
    except ValueError:
        return {"status": r.status_code, "text": r.text[:2000]}


def js_contexts(session, summary):
    html = session.get(f"{ISPU}/", timeout=40).text
    names = set(re.findall(r'src="\./([\w.]+\.js)"', html))
    runtime = next((n for n in names if n.startswith("runtime")), None)
    if runtime:
        body = session.get(f"{ISPU}/{runtime}", timeout=40).text
        names |= {f"{num}.{h}.js" for num, h in re.findall(r'(\d+):"([0-9a-f]{16,24})"', body)}
    hits = []
    pattern = re.compile(r"info-lokacija|kat-cestic|katastarsk|cestic|pretrag|gis/search|/search|geocod|adres", re.I)
    for name in sorted(names):
        try:
            body = session.get(f"{ISPU}/{name}", timeout=60).text
        except Exception:  # noqa: BLE001
            continue
        for m in pattern.finditer(body):
            hits.append({"js": name, "match": m.group(0), "ctx": body[max(0, m.start() - 400): m.start() + 500]})
    save("js_contexts.json.gz", hits)
    summary["js_hits"] = len(hits)
    summary["js_match_counts"] = {}
    for h in hits:
        summary["js_match_counts"][h["match"].lower()] = summary["js_match_counts"].get(h["match"].lower(), 0) + 1


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {"started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        session = cffi.Session(impersonate="chrome")
        session.get(f"{ISPU}/", timeout=60)
        session.get(API + "auth/authz", timeout=60)
        layers = []
        walk(session.get(API + "gis/catalog-izbornik", timeout=60).json(), [], layers)
        save("slojevi.json", layers)
        gp = [la for la in layers if "Građevinska područja" in la["path"]]
        ppv = [la for la in layers if la["label"].get("hr", "").startswith("PPV 1.1.2026. – zemljišta")]
        summary["gp_layers"] = [{k: la[k] for k in ("path", "id", "layers", "hashIdentify", "scales")} for la in gp]
        tests = {}
        for name, (lat, lon) in POINTS.items():
            tests[name] = identify(session, lat, lon, [la for la in gp if la["hashIdentify"]] + ppv)
            time.sleep(0.5)
        save("identify.json", tests)
        summary["identify_sample"] = {k: json.dumps(v, ensure_ascii=False)[:2500] for k, v in list(tests.items())[:3]}
        js_contexts(session, summary)
        # info-lokacija-* za točku: pokušaj nekoliko oblika (x/y u HTRS96).
        x, y = to_htrs(*POINTS["njivice"])
        probes = {}
        for suffix in ("kat-cestica", "prostorne-jedinice", "obuhvat", "nadlezni-odjel"):
            for method, kwargs in (("get", {"params": {"x": x, "y": y}}), ("post", {"json": {"x": x, "y": y}}),
                                   ("post", {"json": {"x": x, "y": y, "scale": 2000}})):
                try:
                    r = getattr(session, method)(API + f"gis/info-lokacija-{suffix}", headers=HEADERS, timeout=40, **kwargs)
                    probes[f"{suffix}:{method}:{list(kwargs.values())[0]}"] = {"status": r.status_code, "body": r.text[:1500]}
                except Exception as exc:  # noqa: BLE001
                    probes[f"{suffix}:{method}"] = {"error": str(exc)[:200]}
                time.sleep(0.3)
        summary["info_lokacija"] = probes
    except Exception:  # noqa: BLE001
        summary["error"] = traceback.format_exc()[-3000:]
    finally:
        summary["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        save("sazetak.json", summary)


if __name__ == "__main__":
    main()
