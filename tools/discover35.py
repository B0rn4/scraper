"""Trideset peti krug: burza.com.hr (regionalni oglasnik, Kvarner i Istra) prema našim
portalima – kuće i zemljišta s našeg područja, koliko prolazi kriterije i koliko ih već
imamo (state.db, redmi.db)."""

import html
import json
import re
import sqlite3
import sys
import time
import traceback
from collections import Counter
from pathlib import Path

import requests
from curl_cffi import requests as cffi

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper import dedupe  # noqa: E402
from scraper.filters import evaluate  # noqa: E402
from scraper.locations import Locator  # noqa: E402
from scraper.models import HOUSE, LAND, REJECT, Listing  # noqa: E402
from scraper.runner import load_config  # noqa: E402
from scraper.text import areas_in_text, parse_number  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "debug-out") / "discovery35"
BASE = "https://burza.com.hr"
RAW = "https://raw.githubusercontent.com/B0rn4/scraper/"
PLACES = ["kvarner-i-istra-crikvenica", "kvarner-i-istra-dramalj", "kvarner-i-istra-jadranovo", "kvarner-i-istra-selce",
          "kvarner-i-istra-kostrena", "kvarner-i-istra-kraljevica", "kvarner-i-istra-matulji", "kvarner-i-istra-opatija-i-okolica",
          "kvarner-i-istra-otok-krk", "kvarner-i-istra-rijeka", "hrvatska-primorsko-goranska-lovran-lovran"]
KINDS = [("nekretnine-kuce-prodaja", HOUSE), ("nekretnine-zemljista-prodaja", LAND)]


def clean(value):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value or "")).split())


def parse_list(page):
    out = []
    for block in re.split(r'<div class="bad" ', page)[1:]:
        link = re.search(r'href="(/oglasi/[^"]+/(\d+))"', block)
        if not link:
            continue
        title = re.search(r'class="bad-title"><a[^>]*>(.*?)</a>', block, re.S)
        price = re.search(r'class="price-primary">([^<]+)<', block)
        text = re.search(r'class="bad-text">(.*?)</p>', block, re.S)
        out.append({"id": link.group(2), "url": BASE + link.group(1), "title": clean(title.group(1)) if title else "",
                    "price": parse_number(price.group(1)) if price and re.search(r"\d", price.group(1)) else None,
                    "snippet": clean(text.group(1)) if text else ""})
    return out


def seen_rows():
    rows = []
    for branch, name in (("state", "state.db"), ("state-redmi", "redmi.db")):
        path = OUT / name
        try:
            path.write_bytes(requests.get(f"{RAW}{branch}/{name}", timeout=60).content)
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            rows += [dict(r) for r in conn.execute(
                "SELECT key, source, kind, jls, price, area, title, settlement, first_seen FROM listings")]
            conn.close()
        except Exception as exc:  # noqa: BLE001
            print(name, exc)
        path.unlink(missing_ok=True)
    return rows


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    s = cffi.Session(impersonate="chrome")
    cfg = load_config()
    locator = Locator()
    summary, items = {}, {}
    try:
        for slug, kind in KINDS:
            for place in PLACES:
                for page in range(1, 6):
                    url = f"{BASE}/oglasi/{slug}/{place}" + (f"?stranica={page}" if page > 1 else "")
                    r = s.get(url, timeout=40)
                    rows = parse_list(r.text)
                    for row in rows:
                        row.update(kind=kind, place=place)
                        items.setdefault(row["id"], row)
                    if len(rows) < 20:
                        break
                    time.sleep(1)
                time.sleep(1)
        summary["items"] = len(items)
        summary["by_place"] = Counter(f"{r['kind']}:{r['place']}" for r in items.values())
        seen = dedupe.Seen(locator)
        for row in seen_rows():
            seen.add(row)
        results, unmatched, matched = Counter(), [], []
        saved = False
        for row in list(items.values())[:250]:
            try:
                page = s.get(row["url"], timeout=40).text
            except Exception:  # noqa: BLE001
                results["greska"] += 1
                continue
            if not saved:
                (OUT / "oglas.html").write_text(page[:300000], encoding="utf-8")
                saved = True
            text = clean(re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", page))
            body = text[text.find(row["title"][:30]):][:4000] if row["title"][:30] in text else text[:4000]
            areas = [a for a in areas_in_text(body) if a >= 20]
            date = re.search(r"(\d{1,2}\.\s?\d{1,2}\.\s?20\d\d\.?)", body)
            agency = bool(re.search(r"agencij|nekretnine d\.o\.o|real estate|ID oglasa agencije|provizij", body, re.I))
            x = Listing("burza", row["id"], row["url"], row["title"], row["kind"], price=row["price"],
                        area=areas[0] if areas else None, location_text=row["place"].replace("kvarner-i-istra-", "").replace("-", " "),
                        description=body[:3000])
            d = evaluate(x, cfg["kriteriji"], locator)
            if d.status == REJECT:
                results["odbijen"] += 1
                continue
            twins = seen.twins(dedupe.row(x, d)) if x.price and x.area else []
            item = {"id": row["id"], "url": row["url"], "title": row["title"][:100], "price": x.price, "area": x.area,
                    "jls": d.jls, "date": date.group(1) if date else "", "agencija": agency}
            if twins:
                results["vec_imamo"] += 1
                item["twins"] = [t["key"] for t in twins[:3]]
                matched.append(item)
            else:
                results["nemamo"] += 1
                unmatched.append(item)
            time.sleep(1)
        summary["results"] = dict(results)
        (OUT / "nemamo.json").write_text(json.dumps(unmatched, ensure_ascii=False, indent=1), encoding="utf-8")
        (OUT / "imamo.json").write_text(json.dumps(matched, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:  # noqa: BLE001
        summary["error"] = traceback.format_exc()[-1500:]
    (OUT / "sazetak.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
