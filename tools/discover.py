"""Otkrivanje izvora podataka: otvara stranice pravim preglednikom i bilježi
koje adrese stranica poziva za dohvat oglasa (XHR/fetch), uz odgovore.

Rezultat ide u direktorij zadan argumentom (workflow ga gura na granu `debug`).
"""

import gzip
import json
import re
import sys
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "debug-out") / "discovery"
MAX_BODY = 400_000

BROWSER_TARGETS = {
    "oglasnik_kuce": "https://www.oglasnik.hr/kuce-prodaja",
    "oglasnik_zemljista": "https://www.oglasnik.hr/zemljista-prodajem",
    "index_home": "https://www.index.hr/oglasi/",
    "index_nekretnine": "https://www.index.hr/oglasi/nekretnine",
    "index_prodaja_kuca": "https://www.index.hr/oglasi/prodaja-kuca",
    "nekretnine_hr_kuce_punat": "https://www.nekretnine.hr/prodaja-samostojeca-kuce/punat/",
}

# Provjera parametara sortiranja i filtera na nekretnine.hr (obični HTTP zahtjevi).
NEKRETNINE_PARAMS = {
    "plain": "https://www.nekretnine.hr/prodaja-samostojeca-kuce/punat/",
    "sort_data": "https://www.nekretnine.hr/prodaja-samostojeca-kuce/punat/?criterio=data&ordine=desc",
    "sort_datamod": "https://www.nekretnine.hr/prodaja-samostojeca-kuce/punat/?criterio=dataModifica&ordine=desc",
    "filters": "https://www.nekretnine.hr/prodaja-samostojeca-kuce/punat/?prezzoMassimo=400000&superficieMinima=70",
    "vikendice": "https://www.nekretnine.hr/prodaja-vikendice/primorsko-goranska-zupanija/",
    "stambene_punat": "https://www.nekretnine.hr/prodaja-stambene-nekretnine/punat/",
    "zemljista_punat": "https://www.nekretnine.hr/prodaja-zemljista/punat/?criterio=data&ordine=desc",
}

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)


def slug(url: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", url.lower().split("//", 1)[-1]).strip("_")[:90]


def browse(page, name: str, url: str) -> None:
    folder = OUT / name
    (folder / "responses").mkdir(parents=True, exist_ok=True)
    log = []

    def on_response(resp):
        req = resp.request
        if req.resource_type not in ("xhr", "fetch", "document"):
            return
        entry = {
            "type": req.resource_type,
            "method": req.method,
            "url": resp.url,
            "status": resp.status,
            "content_type": resp.headers.get("content-type", ""),
            "post_data": (req.post_data or "")[:3000],
        }
        if "json" in entry["content_type"] or req.resource_type in ("xhr", "fetch"):
            try:
                body = resp.body()[:MAX_BODY]
                fname = f"{len(log):03d}_{slug(resp.url)[:60]}.txt"
                (folder / "responses" / fname).write_bytes(body)
                entry["saved"] = fname
            except Exception as exc:  # noqa: BLE001
                entry["body_error"] = str(exc)[:200]
        log.append(entry)

    page.on("response", on_response)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        page.wait_for_timeout(4000)
        for _ in range(4):
            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(1500)
        page.wait_for_load_state("networkidle", timeout=20_000)
    except Exception as exc:  # noqa: BLE001
        log.append({"error": f"{type(exc).__name__}: {str(exc)[:300]}"})
    finally:
        page.remove_listener("response", on_response)

    try:
        (folder / "page.html.gz").write_bytes(gzip.compress(page.content().encode()))
        page.screenshot(path=str(folder / "screenshot.png"), full_page=False)
        links = page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
        (folder / "links.txt").write_text("\n".join(sorted(set(links))), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        log.append({"error_after": str(exc)[:300]})
    (folder / "requests.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")


def check_nekretnine_params() -> None:
    try:
        from curl_cffi import requests as cffi
    except ImportError:
        cffi = None
    folder = OUT / "nekretnine_params"
    folder.mkdir(parents=True, exist_ok=True)
    summary = {}
    for name, url in NEKRETNINE_PARAMS.items():
        try:
            if cffi is not None:
                resp = cffi.get(url, impersonate="chrome", timeout=30)
            else:
                resp = requests.get(url, headers={"User-Agent": UA}, timeout=30)
            html = resp.text
            m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
            item = {"status": resp.status_code}
            if m:
                queries = json.loads(m.group(1))["props"]["pageProps"]["dehydratedState"]["queries"]
                for q in queries:
                    data = q["state"]["data"]
                    if isinstance(data, dict) and "results" in data:
                        item["queryKey"] = q["queryKey"]
                        item["count"] = data.get("count")
                        item["first"] = [
                            {
                                "id": r["realEstate"]["id"],
                                "title": r["realEstate"].get("title"),
                                "price": r["realEstate"]["price"].get("value"),
                                "typology": r["realEstate"]["properties"][0].get("typology", {}).get("name"),
                                "surface": r["realEstate"]["properties"][0].get("surface"),
                            }
                            for r in data["results"][:8]
                        ]
                        break
            summary[name] = item
        except Exception as exc:  # noqa: BLE001
            summary[name] = {"error": str(exc)[:300]}
    (folder / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    check_nekretnine_params()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(user_agent=UA, locale="hr-HR", viewport={"width": 1366, "height": 900})
        page = context.new_page()
        for name, url in BROWSER_TARGETS.items():
            browse(page, name, url)
        browser.close()


if __name__ == "__main__":
    main()
