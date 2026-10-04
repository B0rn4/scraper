"""Drugi krug otkrivanja: provjera API-ja index.hr, SSR stranica oglasnik.hr
i preuzimanje index.hr popisa lokacija (županija → grad/općina → naselje)."""

import gzip
import json
import re
import sys
from pathlib import Path

from curl_cffi import requests as cffi

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "debug-out") / "discovery2"


def get(url, **kw):
    return cffi.get(url, impersonate="chrome", timeout=40, **kw)


def save(name, text):
    (OUT / name).write_bytes(gzip.compress(text.encode("utf-8")))


def index_tests(summary):
    base = "https://www.index.hr/oglasi/api/aditem"
    variants = {
        "list_sort4": f"{base}?module=real-estate&category=houses-for-sale&sortOption=4&page=1",
        "list_sort4_pp50": f"{base}?module=real-estate&category=houses-for-sale&sortOption=4&page=1&itemPerPage=50",
        "list_land": f"{base}?module=real-estate&category=lands-for-sale&sortOption=4&page=1",
        "latest": f"{base}/latest?module=real-estate&category=houses-for-sale",
        "widget": f"{base}/widget-search?module=real-estate&category=houses-for-sale&itemPerPage=50&page=1",
    }
    for name, url in variants.items():
        try:
            r = get(url, headers={"Accept": "application/json"})
            item = {"status": r.status_code, "ct": r.headers.get("content-type"), "bytes": len(r.content)}
            try:
                data = r.json()
                if isinstance(data, dict):
                    item["keys"] = list(data.keys())
                    item["count"] = data.get("count")
                    rows = data.get("data") or []
                    item["n"] = len(rows)
                    item["first"] = [
                        {k: x.get(k) for k in ("code", "title", "price", "cityName", "settlementName", "countyName", "postedTime", "category")}
                        for x in rows[:5]
                    ]
                save(f"index_{name}.json.gz", r.text)
            except Exception as exc:  # noqa: BLE001
                item["json_error"] = str(exc)[:200]
                item["head"] = r.text[:500]
            summary[f"index_{name}"] = item
        except Exception as exc:  # noqa: BLE001
            summary[f"index_{name}"] = {"error": str(exc)[:300]}

    try:
        r = get("https://www.index.hr/oglasi/api/configuration/datasource/location")
        save("index_locations.json.gz", r.text)
        summary["index_locations"] = {"status": r.status_code, "bytes": len(r.content)}
    except Exception as exc:  # noqa: BLE001
        summary["index_locations"] = {"error": str(exc)[:300]}


def oglasnik_tests(summary):
    tests = {
        "kuce_newest": ("https://oglasnik.hr/kuce-prodaja?sort=newest&page=1", {}),
        "kuce_newest_rsc": ("https://oglasnik.hr/kuce-prodaja?sort=newest&page=1", {"RSC": "1"}),
        "zemljista_newest": ("https://oglasnik.hr/zemljista-prodajem?sort=newest&page=1", {}),
        "kuce_plain": ("https://oglasnik.hr/kuce-prodaja", {}),
    }
    for name, (url, headers) in tests.items():
        try:
            r = get(url, headers=headers)
            links = sorted(set(re.findall(r'/(?:kuce-prodaja|zemljista-prodajem)/[a-z0-9\-]+-oglas-\d+', r.text)))
            summary[f"oglasnik_{name}"] = {
                "status": r.status_code,
                "ct": r.headers.get("content-type"),
                "bytes": len(r.content),
                "ad_links": len(links),
                "sample": links[:3],
                "challenge": "challenge-platform" in r.text and len(links) == 0,
            }
            save(f"oglasnik_{name}.html.gz", r.text)
        except Exception as exc:  # noqa: BLE001
            summary[f"oglasnik_{name}"] = {"error": str(exc)[:300]}
    # Jedan oglas, za strukturu detalja.
    first = (summary.get("oglasnik_kuce_newest") or {}).get("sample") or []
    if first:
        r = get("https://oglasnik.hr" + first[0])
        save("oglasnik_detail.html.gz", r.text)
        summary["oglasnik_detail"] = {"status": r.status_code, "bytes": len(r.content), "url": first[0]}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {}
    index_tests(summary)
    oglasnik_tests(summary)
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1)[:5000])


if __name__ == "__main__":
    main()
