"""Četvrti krug: index.hr API iz konteksta stranice (preglednik) i način na
koji oglasnik.hr gradi URL filtra lokacije."""

import gzip
import json
import re
import sys
from pathlib import Path

from curl_cffi import requests as cffi
from playwright.sync_api import sync_playwright

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "debug-out") / "discovery4"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)
FETCH_JS = """async (url) => {
  const r = await fetch(url, {headers: {Accept: 'application/json', 'Content-Type': 'application/json'}, credentials: 'include'});
  return {status: r.status, text: await r.text()};
}"""


def save(name, text):
    (OUT / name).write_bytes(gzip.compress(text.encode("utf-8")))


def index_browser(page, summary):
    page.goto("https://www.index.hr/oglasi/nekretnine/prodaja-kuca", wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(5000)
    res = page.evaluate(FETCH_JS, "/oglasi/api/configuration/datasource/location")
    summary["index_loc_browser"] = {"status": res["status"], "bytes": len(res["text"])}
    save("index_locations.json.gz", res["text"])
    county_id = city_id = None
    try:
        text = res["text"]
        m = re.search(r'"id":"([0-9a-f\-]{36})","name":"Primorsko-goranska"', text) or re.search(
            r'"name":"Primorsko-goranska"[^{}]*?"id":"([0-9a-f\-]{36})"', text
        )
        county_id = m.group(1) if m else None
        m = re.search(r'"id":"([0-9a-f\-]{36})","name":"Opatija"', text) or re.search(
            r'"name":"Opatija"[^{}]*?"id":"([0-9a-f\-]{36})"', text
        )
        city_id = m.group(1) if m else None
        summary["index_ids"] = {"county": county_id, "opatija": city_id, "sample": text[:600]}
    except Exception as exc:  # noqa: BLE001
        summary["index_ids"] = {"error": str(exc)[:300]}

    base = "/oglasi/api/aditem?module=real-estate&sortOption=4&itemPerPage=24"
    tests = {
        "kuce": f"{base}&category=houses-for-sale&page=1",
        "zemljista": f"{base}&category=lands-for-sale&page=1",
    }
    if county_id:
        tests["kuce_pgz"] = f"{base}&category=houses-for-sale&page=1&countyId={county_id}"
        tests["zemljista_pgz_p2"] = f"{base}&category=lands-for-sale&page=2&countyId={county_id}"
    if county_id and city_id:
        tests["kuce_opatija"] = f"{base}&category=houses-for-sale&page=1&countyId={county_id}&cityId={city_id}"
    for name, url in tests.items():
        res = page.evaluate(FETCH_JS, url)
        item = {"status": res["status"], "bytes": len(res["text"]), "url": url}
        try:
            data = json.loads(res["text"])
            rows = data.get("data") or []
            item.update(count=data.get("count"), n=len(rows), nextPage=data.get("nextPage"))
            item["counties"] = sorted({str(x.get("countyName")) for x in rows})
            item["cities"] = sorted({str(x.get("cityName")) for x in rows})[:20]
            item["first"] = [
                {k: x.get(k) for k in ("code", "title", "price", "previousPrice", "cityName", "settlementName", "postedTime", "smartLink")}
                for x in rows[:4]
            ]
            save(f"index_{name}.json.gz", res["text"])
        except Exception as exc:  # noqa: BLE001
            item["error"] = str(exc)[:200]
            item["head"] = res["text"][:300]
        summary[f"index_{name}"] = item

    # Radi li isti poziv izvan preglednika, s kolačićima iz preglednika?
    cookies = {c["name"]: c["value"] for c in page.context.cookies()}
    for name, kwargs in {
        "cffi_cookies": dict(impersonate="chrome", cookies=cookies),
        "cffi_cookies_referer": dict(
            impersonate="chrome",
            cookies=cookies,
            headers={"Referer": "https://www.index.hr/oglasi/nekretnine/prodaja-kuca", "Accept": "application/json", "Content-Type": "application/json"},
        ),
    }.items():
        try:
            r = cffi.get("https://www.index.hr" + tests["kuce"], timeout=40, **kwargs)
            summary[f"index_{name}"] = {"status": r.status_code, "bytes": len(r.content), "head": r.text[:120]}
        except Exception as exc:  # noqa: BLE001
            summary[f"index_{name}"] = {"error": str(exc)[:300]}
    summary["index_cookie_names"] = sorted(cookies)


def oglasnik_js(page, summary):
    page.goto("https://oglasnik.hr/kuce-prodaja?sort=newest", wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(4000)
    scripts = page.eval_on_selector_all("script[src]", "els => els.map(e => e.src)")
    hits = []
    for src in scripts:
        try:
            body = page.evaluate("async (u) => (await fetch(u)).text()", src)
        except Exception:  # noqa: BLE001
            continue
        for m in re.finditer(r"ad_location", body):
            hits.append({"src": src.rsplit("/", 1)[-1], "ctx": body[max(0, m.start() - 400): m.start() + 400]})
    summary["oglasnik_js_hits"] = len(hits)
    (OUT / "oglasnik_js_hits.json").write_text(json.dumps(hits[:40], ensure_ascii=False, indent=1), encoding="utf-8")

    # Pokušaj kroz sučelje: otvori filtere i odaberi županiju.
    try:
        for label in ("Filteri", "Filtriraj", "Više filtera"):
            btn = page.get_by_text(label, exact=False).first
            if btn.count():
                btn.click(timeout=3000)
                page.wait_for_timeout(1000)
                break
        page.get_by_text("Odaberite županiju").first.click(timeout=5000)
        page.wait_for_timeout(800)
        page.get_by_text("Primorsko-goranska", exact=True).first.click(timeout=5000)
        page.wait_for_timeout(2500)
        for label in ("Prikaži", "Pretraži", "Primijeni", "Traži"):
            btn = page.get_by_role("button", name=re.compile(label, re.I)).first
            if btn.count():
                btn.click(timeout=3000)
                break
        page.wait_for_timeout(4000)
        summary["oglasnik_ui_url"] = page.url
    except Exception as exc:  # noqa: BLE001
        summary["oglasnik_ui_error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        summary["oglasnik_ui_url"] = page.url
    page.screenshot(path=str(OUT / "oglasnik_ui.png"))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(user_agent=UA, locale="hr-HR", viewport={"width": 1366, "height": 900})
        page = context.new_page()
        for fn in (index_browser, oglasnik_js):
            try:
                fn(page, summary)
            except Exception as exc:  # noqa: BLE001
                summary[f"{fn.__name__}_error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        browser.close()
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1)[:6000])


if __name__ == "__main__":
    main()
