"""Peti krug: oglasnik.hr filter županije kroz sučelje; index.hr API bez
preglednika (kolačić iz obične posjete stranici)."""

import json
import re
import sys
from pathlib import Path

from curl_cffi import requests as cffi
from playwright.sync_api import sync_playwright

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "debug-out") / "discovery5"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)


def index_session(summary):
    s = cffi.Session(impersonate="chrome")
    r1 = s.get("https://www.index.hr/oglasi/nekretnine/prodaja-kuca", timeout=40)
    summary["index_page"] = {"status": r1.status_code, "cookies": sorted(s.cookies.keys())}
    url = "https://www.index.hr/oglasi/api/aditem?module=real-estate&sortOption=4&itemPerPage=24&category=houses-for-sale&page=1&countyId=95c57539-6835-4b89-8ddd-a5de2100686e"
    r2 = s.get(url, headers={"Accept": "application/json", "Content-Type": "application/json"}, timeout=40)
    item = {"status": r2.status_code, "bytes": len(r2.content)}
    try:
        data = r2.json()
        rows = data.get("data") or []
        item.update(count=data.get("count"), n=len(rows), counties=sorted({str(x.get("countyName")) for x in rows}))
    except Exception as exc:  # noqa: BLE001
        item["head"] = r2.text[:200]
    summary["index_api_session"] = item


def oglasnik_ui(page, summary):
    page.goto("https://oglasnik.hr/kuce-prodaja?sort=newest", wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(3000)
    for name in ("Prihvaćam sve", "Ne prihvaćam"):
        btn = page.get_by_role("button", name=name)
        if btn.count():
            btn.first.click()
            break
    page.get_by_text("Filtriraj", exact=True).first.click(timeout=8000)
    page.wait_for_timeout(1000)
    page.get_by_text("Županija", exact=True).first.click(timeout=8000)
    page.wait_for_timeout(1200)
    page.screenshot(path=str(OUT / "oglasnik_zupanije.png"))
    page.get_by_text("Primorsko-goranska", exact=True).first.click(timeout=8000)
    page.wait_for_timeout(1500)
    page.screenshot(path=str(OUT / "oglasnik_odabrano.png"))
    # Ako je otvoren podizbornik, vrati se na popis filtera.
    for label in ("Natrag", "Potvrdi", "Spremi", "Odaberi"):
        btn = page.get_by_text(label, exact=True)
        if btn.count():
            btn.first.click()
            page.wait_for_timeout(800)
            break
    page.get_by_text("Prikaži rezultate", exact=False).first.click(timeout=8000)
    page.wait_for_timeout(4000)
    summary["oglasnik_url_after_county"] = page.url
    html = page.content()
    summary["oglasnik_ads_after"] = len(set(re.findall(r"oglas-(\d+)", html)))
    page.screenshot(path=str(OUT / "oglasnik_rezultati.png"))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {}
    try:
        index_session(summary)
    except Exception as exc:  # noqa: BLE001
        summary["index_error"] = str(exc)[:300]
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_context(user_agent=UA, locale="hr-HR", viewport={"width": 1366, "height": 900}).new_page()
        try:
            oglasnik_ui(page, summary)
        except Exception as exc:  # noqa: BLE001
            summary["oglasnik_error"] = f"{type(exc).__name__}: {str(exc)[:400]}"
            summary["oglasnik_url"] = page.url
            page.screenshot(path=str(OUT / "oglasnik_greska.png"))
        browser.close()
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
