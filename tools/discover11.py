"""Jedanaesti krug: (1) kako index.hr učitava sam oglas (opis za opasne izraze) i
(2) je li Plan približnih vrijednosti (ISPU / NIPP, cjenovni blokovi) dostupan
programski (WMS/WFS) i što vraća za točku (npr. središte Krka)."""

import gzip
import json
import re
import sys
import time
import traceback
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlparse

from curl_cffi import requests as cffi

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.http import Http  # noqa: E402
from scraper.locations import Locator  # noqa: E402
from scraper.runner import load_config  # noqa: E402
from scraper.sources.index_oglasi import BASE, JSON_HEADERS, IndexOglasi  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "debug-out") / "discovery11"
DEADLINE = time.monotonic() + 19 * 60
MAX_BODY = 600_000
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36")
# Točke za probu Plana približnih vrijednosti (lat, lon).
POINTS = {"krk_centar": (45.0272, 14.5753), "malinska": (45.1245, 14.5277),
          "crikvenica": (45.1767, 14.6926), "rijeka_korzo": (45.3271, 14.4422), "opatija": (45.3377, 14.3058)}
PPV_WORDS = re.compile(r"cjenov|priblizn|približn|ppv|nekretnin|vrijednost", re.I)
SERVICE_URL = re.compile(r"""https?://[^\s"'<>\\]+?(?:geoserver|/wms|/wfs|/ows|mapserver|MapServer|arcgis/rest)[^\s"'<>\\]*""", re.I)
ISPU_HOSTS = ["https://ispu.mgipu.hr/", "https://geoportal.nipp.hr/", "https://enekretnine.mgipu.hr/",
              "https://e-nekretnine.mgipu.hr/", "https://nekretnine.mgipu.hr/"]


def save(name, data):
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, (dict, list)):
        data = json.dumps(data, ensure_ascii=False, indent=1)
    if isinstance(data, str):
        data = data.encode("utf-8")
    path.write_bytes(gzip.compress(data[:MAX_BODY]) if name.endswith(".gz") else data[:MAX_BODY])


def slug(url: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", url.lower().split("//", 1)[-1]).strip("_")[:70]


def probe(session, url, name=None, **kwargs) -> dict:
    try:
        r = session.get(url, timeout=40, **kwargs)
    except Exception as exc:  # noqa: BLE001
        return {"url": url, "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
    item = {"url": url, "status": r.status_code, "ctype": r.headers.get("content-type", ""), "bytes": len(r.content),
            "final_url": str(r.url) if str(r.url) != url else None, "head": r.text[:300]}
    if name:
        save(name, r.content)
        item["saved"] = name
    return item


def capture(page, url, folder, wait_ms=6000, actions=None) -> dict:
    """Otvori stranicu u pregledniku i zabilježi XHR/fetch zahtjeve (s odgovorima)."""
    log = []

    def on_response(resp):
        req = resp.request
        if req.resource_type not in ("xhr", "fetch", "document", "script"):
            return
        entry = {"type": req.resource_type, "method": req.method, "url": resp.url[:600], "status": resp.status,
                 "ctype": resp.headers.get("content-type", ""), "post": (req.post_data or "")[:2000]}
        if req.resource_type in ("xhr", "fetch") or "json" in entry["ctype"] or "xml" in entry["ctype"]:
            try:
                fname = f"{folder}/r{len(log):03d}_{slug(resp.url)[:50]}.txt.gz"
                save(fname, resp.body())
                entry["saved"] = fname
            except Exception as exc:  # noqa: BLE001
                entry["body_error"] = str(exc)[:150]
        log.append(entry)

    page.on("response", on_response)
    result = {"url": url}
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(wait_ms)
        if actions:
            result["actions"] = actions(page)
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
    finally:
        page.remove_listener("response", on_response)
    try:
        save(f"{folder}/page.html.gz", page.content())
        save(f"{folder}/text.txt", page.evaluate("() => document.body ? document.body.innerText : ''"))
        page.screenshot(path=str(OUT / folder / "screenshot.png"))
    except Exception as exc:  # noqa: BLE001
        result["after_error"] = str(exc)[:200]
    save(f"{folder}/requests.json", log)
    result["requests"] = len(log)
    result["api"] = [f"{e['method']} {e['status']} {e['url'][:200]}" for e in log
                     if e["type"] in ("xhr", "fetch")][:60]
    return result


# ---------------------------------------------------------------- index.hr

def index_detail(summary, page):
    cfg = load_config()
    http = Http(delay=1.5)
    src = IndexOglasi(http, Locator(), cfg["kriteriji"])
    raw = src._api("houses-for-sale", 1)
    items = (raw.get("data") or [])[:3]
    save("index/list_raw.json", raw)
    summary["index_list_keys"] = sorted(items[0]) if items else []
    session = http.session
    out = []
    for x in items:
        code, iid = x.get("code"), x.get("id")
        url = f"{BASE}/nekretnine/prodaja-kuca/oglas/{x.get('smartLink', '')}/{code}"
        tries = {"html": probe(session, url, f"index/{code}_page.html.gz")}
        html = (OUT / f"index/{code}_page.html.gz")
        if html.exists():
            text = gzip.decompress(html.read_bytes()).decode("utf-8", "replace")
            tries["html"].update(
                next_data="__NEXT_DATA__" in text, nuxt="__NUXT__" in text, ld_json="ld+json" in text,
                og_description=(re.search(r'<meta[^>]+property="og:description"[^>]+content="([^"]{0,300})', text) or [None, None])[1],
                description_word=len(re.findall(r"[Oo]pis", text)))
        for name, path in {
            "api_code": f"/api/aditem/{code}", "api_id": f"/api/aditem/{iid}",
            "api_detail_code": f"/api/aditem/detail/{code}", "api_details_code": f"/api/aditem/details/{code}",
            "api_code_q": f"/api/aditem?code={code}", "api_by_code": f"/api/aditem/code/{code}",
            "api_smart": f"/api/aditem/smartlink/{x.get('smartLink', '')}/{code}",
        }.items():
            if iid is None and "{iid}" in path:
                continue
            tries[name] = probe(session, BASE + path, f"index/{code}_{name}.txt.gz", headers=JSON_HEADERS)
            time.sleep(1)
        out.append({"code": code, "id": iid, "url": url, "tries": tries})
    summary["index_detail_cffi"] = out
    if items and page is not None:
        x = items[0]
        url = f"{BASE}/nekretnine/prodaja-kuca/oglas/{x.get('smartLink', '')}/{x.get('code')}"
        summary["index_detail_browser"] = capture(page, url, "index/browser", wait_ms=6000)


# ---------------------------------------------------------------- ISPU / NIPP

def find_services(text: str) -> set[str]:
    found = set()
    for m in SERVICE_URL.finditer(text):
        u = m.group(0).rstrip(".,;)")
        found.add(u.split("?", 1)[0])
    return found


def js_hits(session, base_url, html, folder) -> tuple[list, set]:
    """Skripte stranice: adrese servisa i spomeni cjenovnih blokova / PPV."""
    hits, services = [], set()
    scripts = re.findall(r'<script[^>]+src="([^"]+)"', html)
    for src in scripts[:25]:
        url = urljoin(base_url, src)
        try:
            body = session.get(url, timeout=40).text
        except Exception:  # noqa: BLE001
            continue
        services |= find_services(body)
        for m in re.finditer(r"[Cc]jenov|[Pp]ribli[zž]n|PPV|ppv_|geoserver|/wms|/wfs", body):
            hits.append({"src": url.rsplit("/", 1)[-1][:60], "ctx": body[max(0, m.start() - 200): m.start() + 250]})
            if len(hits) > 300:
                break
    save(f"{folder}/js_hits.json", hits[:300])
    return hits, services


def capabilities(session, base: str) -> dict:
    """GetCapabilities za WMS i WFS; slojevi čiji naziv spominje cijene/vrijednosti."""
    out = {}
    for service, version in (("WMS", "1.1.1"), ("WFS", "2.0.0")):
        url = f"{base}?{urlencode({'service': service, 'request': 'GetCapabilities', 'version': version})}"
        try:
            r = session.get(url, timeout=60)
        except Exception as exc:  # noqa: BLE001
            out[service] = {"error": str(exc)[:200]}
            continue
        text = r.text
        layers = re.findall(r"<(?:\w+:)?Name>([^<]+)</(?:\w+:)?Name>\s*<(?:\w+:)?Title>([^<]*)</(?:\w+:)?Title>", text)
        out[service] = {"status": r.status_code, "ctype": r.headers.get("content-type", ""), "bytes": len(text),
                        "layers": len(layers), "ppv_layers": [lt for lt in layers if PPV_WORDS.search(" ".join(lt))][:40],
                        "head": text[:200] if r.status_code != 200 else None}
        if r.status_code == 200 and len(text) > 500:
            save(f"ispu/caps/{slug(base)}_{service}.xml.gz", text)
    return out


def feature_info(session, base: str, layer: str) -> dict:
    out = {}
    for name, (lat, lon) in POINTS.items():
        if time.monotonic() > DEADLINE:
            break
        d = 0.0005
        params = {"service": "WMS", "version": "1.1.1", "request": "GetFeatureInfo", "layers": layer,
                  "query_layers": layer, "styles": "", "srs": "EPSG:4326",
                  "bbox": f"{lon - d},{lat - d},{lon + d},{lat + d}", "width": 101, "height": 101,
                  "x": 50, "y": 50, "info_format": "application/json", "feature_count": 5}
        try:
            r = session.get(f"{base}?{urlencode(params)}", timeout=40)
            out[name] = {"status": r.status_code, "ctype": r.headers.get("content-type", ""), "body": r.text[:1500]}
        except Exception as exc:  # noqa: BLE001
            out[name] = {"error": str(exc)[:200]}
    params = {"service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": layer, "count": 3,
              "outputFormat": "application/json"}
    try:
        r = session.get(f"{base.replace('/wms', '/wfs')}?{urlencode(params)}", timeout=60)
        out["wfs_sample"] = {"status": r.status_code, "ctype": r.headers.get("content-type", ""), "body": r.text[:3000]}
    except Exception as exc:  # noqa: BLE001
        out["wfs_sample"] = {"error": str(exc)[:200]}
    return out


def catalog(session) -> dict:
    """Katalog metapodataka NIPP-a (GeoNetwork): zapisi o cjenovnim blokovima / PPV."""
    out = {}
    gn = "https://geoportal.nipp.hr/geonetwork/srv"
    for word in ("cjenovni blokovi", "približnih vrijednosti"):
        out[f"q_{word}"] = probe(session, f"{gn}/hrv/q?{urlencode({'any': word, '_content_type': 'json', 'fast': 'index'})}",
                                 f"ispu/catalog_q_{slug(word)}.json.gz")
        try:
            r = session.post(f"{gn}/api/search/records/_search", timeout=40,
                             headers={"Content-Type": "application/json", "Accept": "application/json"},
                             data=json.dumps({"query": {"query_string": {"query": word}}, "size": 20}))
            out[f"es_{word}"] = {"status": r.status_code, "bytes": len(r.content), "head": r.text[:300]}
            save(f"ispu/catalog_es_{slug(word)}.json.gz", r.content)
        except Exception as exc:  # noqa: BLE001
            out[f"es_{word}"] = {"error": str(exc)[:200]}
        csw = {"service": "CSW", "version": "2.0.2", "request": "GetRecords", "typeNames": "csw:Record",
               "resultType": "results", "elementSetName": "full", "constraintLanguage": "CQL_TEXT",
               "constraint_language_version": "1.1.0", "constraint": f"AnyText like '%{word.split()[0]}%'",
               "maxRecords": 20}
        out[f"csw_{word}"] = probe(session, f"{gn}/hrv/csw?{urlencode(csw)}", f"ispu/catalog_csw_{slug(word)}.xml.gz")
    return out


def ispu(summary, page):
    session = cffi.Session(impersonate="chrome")
    services: set[str] = set()
    hosts = {}
    for url in ISPU_HOSTS:
        item = probe(session, url, f"ispu/{slug(url)}.html.gz")
        hosts[url] = item
        path = OUT / f"ispu/{slug(url)}.html.gz"
        if item.get("status") == 200 and path.exists():
            html = gzip.decompress(path.read_bytes()).decode("utf-8", "replace")
            services |= find_services(html)
            hits, found = js_hits(session, item.get("final_url") or url, html, f"ispu/{slug(url)}")
            services |= found
            item["js_hits"] = len(hits)
    summary["ispu_hosts"] = hosts
    summary["ispu_catalog"] = catalog(session)
    for f in (OUT / "ispu").glob("catalog_*"):
        try:
            services |= find_services(gzip.decompress(f.read_bytes()).decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001
            pass

    if page is not None:
        def click_ppv(p):
            clicked = []
            for pattern in (r"Cjenovni", r"Približn", r"Tržište nekretnina|eNekretnine"):
                try:
                    el = p.get_by_text(re.compile(pattern, re.I)).first
                    if el.count():
                        el.click(timeout=4000)
                        p.wait_for_timeout(3000)
                        clicked.append(pattern)
                except Exception as exc:  # noqa: BLE001
                    clicked.append(f"{pattern}: {type(exc).__name__}")
            return clicked
        for url in ("https://ispu.mgipu.hr/", "https://geoportal.nipp.hr/"):
            if time.monotonic() > DEADLINE:
                break
            folder = f"ispu/browser_{slug(url)}"
            res = capture(page, url, folder, wait_ms=8000, actions=click_ppv)
            summary[f"browser_{slug(url)}"] = res
            log = json.loads((OUT / folder / "requests.json").read_text(encoding="utf-8"))
            for e in log:
                services |= find_services(e["url"])
                if e.get("saved"):
                    try:
                        services |= find_services(gzip.decompress((OUT / e["saved"]).read_bytes()).decode("utf-8", "replace"))
                    except Exception:  # noqa: BLE001
                        pass

    services = sorted({s for s in services if urlparse(s).netloc})
    summary["services_found"] = services[:80]
    caps = {}
    for base in services[:20]:
        if time.monotonic() > DEADLINE:
            break
        if re.search(r"\.(js|css|png|jpg|svg)$", base):
            continue
        caps[base] = capabilities(session, base)
    # Uobičajene adrese GeoServera, ako ih stranice ne otkriju.
    for base in ("https://ispu.mgipu.hr/geoserver/wms", "https://ispu.mgipu.hr/geoserver/ows",
                 "https://geoportal.nipp.hr/geoserver/wms"):
        if base not in caps and time.monotonic() < DEADLINE:
            caps[base] = capabilities(session, base)
    summary["capabilities"] = caps
    info = {}
    for base, c in caps.items():
        for layer, title in (c.get("WMS") or {}).get("ppv_layers", [])[:6]:
            if time.monotonic() > DEADLINE:
                break
            info[f"{base} | {layer} | {title}"] = feature_info(session, base, layer)
    summary["feature_info"] = info


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {"started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    pw = browser = page = None
    try:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch()
        page = browser.new_page(user_agent=UA, locale="hr-HR", viewport={"width": 1400, "height": 900})
    except Exception as exc:  # noqa: BLE001
        summary["browser_error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
    for name, step in (("index", index_detail), ("ispu", ispu)):
        try:
            step(summary, page)
        except Exception:  # noqa: BLE001
            summary[f"{name}_error"] = traceback.format_exc()[-2000:]
        finally:
            save("sazetak.json", summary)
    if browser:
        browser.close()
    if pw:
        pw.stop()
    summary["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    save("sazetak.json", summary)


if __name__ == "__main__":
    main()
