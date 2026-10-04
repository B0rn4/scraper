"""Treći krug otkrivanja: index.hr API s ispravnim zaglavljima i filtrom
lokacije, te parametar lokacije na oglasnik.hr."""

import gzip
import json
import re
import sys
from pathlib import Path

from curl_cffi import requests as cffi

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "debug-out") / "discovery3"
JSON_HEADERS = {"Accept": "application/json", "Content-Type": "application/json"}


def get(url, **kw):
    return cffi.get(url, impersonate="chrome", timeout=40, **kw)


def save(name, text):
    (OUT / name).write_bytes(gzip.compress(text.encode("utf-8")))


def index_tests(summary):
    loc = get("https://www.index.hr/oglasi/api/configuration/datasource/location", headers=JSON_HEADERS)
    summary["index_locations"] = {"status": loc.status_code, "bytes": len(loc.content)}
    save("index_locations.json.gz", loc.text)
    county_id = city_id = None
    try:
        data = loc.json()
        text = json.dumps(data, ensure_ascii=False)
        m = re.search(r'\{"id":\s*"([^"]+)",\s*"name":\s*"Primorsko-goranska"', text)
        if not m:
            m = re.search(r'"id":\s*"([0-9a-f\-]{36})"[^{}]*"name":\s*"Primorsko-goranska"', text)
        county_id = m.group(1) if m else None
        m = re.search(r'"id":\s*"([0-9a-f\-]{36})"[^{}]*"name":\s*"Opatija"', text)
        city_id = m.group(1) if m else None
        summary["index_ids"] = {"county": county_id, "opatija": city_id, "top_keys": list(data.keys())[:10] if isinstance(data, dict) else type(data).__name__}
    except Exception as exc:  # noqa: BLE001
        summary["index_ids"] = {"error": str(exc)[:300], "head": loc.text[:300]}

    base = "https://www.index.hr/oglasi/api/aditem?module=real-estate&sortOption=4&itemPerPage=24"
    variants = {
        "kuce": f"{base}&category=houses-for-sale&page=1",
        "kuce_p2": f"{base}&category=houses-for-sale&page=2",
        "zemljista": f"{base}&category=lands-for-sale&page=1",
    }
    if county_id:
        variants["kuce_pgz"] = f"{base}&category=houses-for-sale&page=1&countyId={county_id}"
        variants["zemljista_pgz"] = f"{base}&category=lands-for-sale&page=1&countyId={county_id}"
    if county_id and city_id:
        variants["kuce_opatija"] = f"{base}&category=houses-for-sale&page=1&countyId={county_id}&cityId={city_id}"
    for name, url in variants.items():
        try:
            r = get(url, headers=JSON_HEADERS)
            item = {"status": r.status_code, "bytes": len(r.content), "url": url}
            if r.status_code == 200:
                data = r.json()
                rows = data.get("data") or []
                item.update(count=data.get("count"), n=len(rows), keys=list(data.keys()))
                item["first"] = [
                    {k: x.get(k) for k in ("code", "title", "price", "previousPrice", "cityName", "settlementName", "countyName", "postedTime")}
                    for x in rows[:6]
                ]
                item["counties"] = sorted({x.get("countyName") for x in rows})
                save(f"index_{name}.json.gz", r.text)
            else:
                item["head"] = r.text[:300]
            summary[f"index_{name}"] = item
        except Exception as exc:  # noqa: BLE001
            summary[f"index_{name}"] = {"error": str(exc)[:300]}


def oglasnik_payload(html):
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', html, re.S)
    return "".join(json.loads('"' + c + '"') for c in chunks)


def oglasnik_tests(summary):
    base = "https://oglasnik.hr/kuce-prodaja?sort=newest&page=1"
    variants = {
        "ad_location": f"{base}&ad_location=4559",
        "ad_location_arr": f"{base}&ad_location[]=4559",
        "ad_location_2": f"{base}&ad_location_2=4559",
        "location": f"{base}&location=4559",
        "path_pgz": "https://oglasnik.hr/kuce-prodaja/primorsko-goranska?sort=newest&page=1",
    }
    for name, url in variants.items():
        try:
            r = get(url)
            payload = oglasnik_payload(r.text)
            ads = re.findall(r'"ad":\{"id":(\d+)', payload)
            pgz = len(re.findall(r'"ad":\{"id":\d+,.{0,400}?"name":"Primorsko-goranska"', payload, re.S))
            total = re.search(r'"total":(\d+)', payload)
            summary[f"oglasnik_{name}"] = {
                "status": r.status_code,
                "ads": len(set(ads)),
                "ads_in_pgz": pgz,
                "total": int(total.group(1)) if total else None,
            }
        except Exception as exc:  # noqa: BLE001
            summary[f"oglasnik_{name}"] = {"error": str(exc)[:300]}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {}
    index_tests(summary)
    oglasnik_tests(summary)
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1)[:6000])


if __name__ == "__main__":
    main()
