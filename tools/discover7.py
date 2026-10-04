"""Faza 2a – otkrivanje: vender.hr (WordPress API), oglasi.hr (Osclass pretraga),
trazimstan.hr (preglednik) i gohome.hr (pretrage običnim jezikom)."""

import base64
import gzip
import json
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import quote

from curl_cffi import requests as cffi
from playwright.sync_api import sync_playwright

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "debug-out") / "discovery7"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)


def save(name, text):
    (OUT / name).write_bytes(gzip.compress(text.encode("utf-8")))


def get(s, url, **kw):
    return s.get(url, timeout=40, **kw)


def vender(s, summary):
    tests = {
        "types": "https://vender.hr/wp-json/wp/v2/types",
        "taxonomies": "https://vender.hr/wp-json/wp/v2/taxonomies",
        "zupanija_page": "https://vender.hr/zupanija/primorsko-goranska/",
        "feed": "https://vender.hr/feed/?post_type=property",
    }
    for name, url in tests.items():
        try:
            r = get(s, url)
            summary[f"vender_{name}"] = {"status": r.status_code, "bytes": len(r.content), "head": r.text[:300]}
            save(f"vender_{name}.gz", r.text)
        except Exception as exc:  # noqa: BLE001
            summary[f"vender_{name}"] = {"error": str(exc)[:200]}
    # Ako postoji post type s REST bazom, dohvati nekoliko nekretnina.
    try:
        types = get(s, tests["types"]).json()
        for key, t in types.items():
            if "propert" in key or "nekretn" in key:
                base = t.get("rest_base") or key
                r = get(s, f"https://vender.hr/wp-json/wp/v2/{base}?per_page=5")
                summary["vender_items"] = {"base": base, "status": r.status_code, "head": r.text[:1500]}
                save("vender_items.gz", r.text)
        tax = get(s, tests["taxonomies"]).json()
        summary["vender_tax"] = {k: v.get("rest_base") for k, v in tax.items()}
    except Exception as exc:  # noqa: BLE001
        summary["vender_items_error"] = str(exc)[:200]


def oglasi(s, summary):
    for name, url in {
        "newest": "https://oglasi.hr/search/category,nekretnine/sOrder,dt_pub_date/iOrderType,desc",
        "home": "https://oglasi.hr/",
    }.items():
        r = get(s, url)
        items = sorted(set(re.findall(r'href="(https://oglasi\.hr/nekretnine/[^"]+_i\d+)"', r.text)))
        cats = sorted(set(re.findall(r'href="(https://oglasi\.hr/(?:nekretnine/)?[a-z\-]+)"', r.text)))
        summary[f"oglasi_{name}"] = {"status": r.status_code, "items": len(items), "sample": items[:8], "cats": cats[:40]}
        save(f"oglasi_{name}.gz", r.text)


def gohome(s, summary):
    queries = [
        "kuća Krk prodaja Najnovije",
        "kuće Primorsko-goranska prodaja Najnovije",
        "građevinsko zemljište Opatija prodaja Najnovije",
        "kuće Rijeka prodaja do 400000 eura barem 70 m2 Najnovije",
        "kuća Kostrena prodaja Zadnjih 7 dana",
    ]
    for i, q in enumerate(queries):
        url = f"https://www.gohome.hr/nekretnine.aspx?q={quote(q)}"
        try:
            r = get(s, url)
            h = r.text
            doms = Counter(d.strip() for d in re.findall(r'class="source">([^<]+)<', h))
            dates = re.findall(r'class="indexed">([^<]+)<', h)
            titles = re.findall(r'<span itemprop="name">([^<]+)</span>', h)
            decoded = []
            for d in re.findall(r"RedirectTo\.aspx\?data=([A-Za-z0-9_\-=]+)", h)[:5]:
                try:
                    decoded.append(json.loads(base64.urlsafe_b64decode(d + "=" * (-len(d) % 4)))["Izvor"])
                except Exception:  # noqa: BLE001
                    pass
            total = re.search(r"all_number[^>]*>(.*?)</p>", h, re.S)
            summary[f"gohome_{i}"] = {
                "q": q, "status": r.status_code, "results": len(titles), "domains": dict(doms),
                "dates": dates[:12], "titles": titles[:10], "urls": decoded,
                "total": re.sub(r"<[^>]+>", " ", total.group(1)) if total else None,
            }
            save(f"gohome_{i}.html.gz", h)
        except Exception as exc:  # noqa: BLE001
            summary[f"gohome_{i}"] = {"q": q, "error": str(exc)[:200]}


def trazimstan(summary):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_context(user_agent=UA, locale="hr-HR").new_page()
        calls = []
        page.on("response", lambda r: calls.append({"url": r.url, "status": r.status, "ct": r.headers.get("content-type", "")})
                if r.request.resource_type in ("xhr", "fetch") else None)
        try:
            page.goto("https://trazimstan.hr/search", wait_until="networkidle", timeout=60_000)
            page.wait_for_timeout(3000)
            page.screenshot(path=str(OUT / "trazimstan.png"))
            text = page.inner_text("body")
            summary["trazimstan"] = {
                "calls": [c for c in calls if "trazimstan" in c["url"]][:30],
                "text": text[:2000],
                "links": sorted(set(page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")))[:80],
            }
            for c in calls:
                if "trazimstan" in c["url"] and "json" in c["ct"]:
                    try:
                        body = page.evaluate("async (u) => (await fetch(u)).text()", c["url"])
                        save("trazimstan_" + re.sub(r"[^a-z0-9]+", "_", c["url"].lower())[-60:] + ".json.gz", body)
                    except Exception:  # noqa: BLE001
                        pass
        except Exception as exc:  # noqa: BLE001
            summary["trazimstan_error"] = str(exc)[:300]
        browser.close()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {}
    s = cffi.Session(impersonate="chrome")
    for fn in (vender, oglasi, gohome):
        try:
            fn(s, summary)
        except Exception as exc:  # noqa: BLE001
            summary[f"{fn.__name__}_error"] = str(exc)[:300]
    trazimstan(summary)
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1)[:4000])


if __name__ == "__main__":
    main()
