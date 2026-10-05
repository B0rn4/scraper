"""Dvadeset deveti krug (faza 5): realestatecroatia.com (sustav Agentor, oglasi agencija)
prema našim portalima – ispravno čitanje.

Popis: list.asp?vrsta=1 (kuće) / 3 (zemljišta), akcija=1 (prodaja), mjesto=…,
sort=objekt_id&smjer=desc (najnoviji prvi), cijenaDo=…; cijena je zapisana "530,000 €".
Površina je samo na stranici oglasa ("Površina: 86 m2", "Okućnica: 170 m2").
Za oglase koji prolaze naše kriterije: ima li ih već u našoj bazi (svi portali, i
Njuškalo s Redmija). Uz to proba nove stranice realestatecroatia.hr."""

import json
import re
import sqlite3
import sys
import traceback
from collections import Counter, defaultdict
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper import dedupe  # noqa: E402
from scraper.filters import evaluate  # noqa: E402
from scraper.http import Http  # noqa: E402
from scraper.locations import Locator  # noqa: E402
from scraper.models import HOUSE, LAND, REJECT, Listing  # noqa: E402
from scraper.runner import load_config  # noqa: E402
from scraper.text import fold, parse_number  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "debug-out") / "discovery29"
RC = "https://www.realestatecroatia.com/hrv/"
RAW = "https://raw.githubusercontent.com/B0rn4/scraper/"
MAX_DETAILS = 420


def save(name, data):
    (OUT / name).write_text(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=1, default=str),
                            encoding="utf-8")


def clean(html):
    return " ".join(re.sub(r"<[^>]+>", " ", html or "").replace("&#8364;", "€").replace("&nbsp;", " ").split())


def parse_list(html):
    out = []
    for block in re.findall(r"<li[^>]*>(.*?)</li>", html, re.S):
        m = re.search(r"detail\.asp\?id=(\d+)", block)
        if not m:
            continue
        price = re.search(r'class="cijena">\s*([\d.,]+)\s*&#8364;', block)
        place = re.search(r"Mjesto:\s*(?:<br\s*/?>\s*)*<strong>([^<]+)</strong>", block)
        kind = re.search(r"Vrsta:\s*<strong>([^<]+)</strong>", block)
        title = re.search(r'<strong><a href="detail\.asp\?id=\d+"[^>]*>(.*?)</a>', block, re.S)
        agency = re.search(r'showconn\.asp\?id=(\d+)"><strong>([^<]+)', block)
        snippet = re.search(r"</a></strong>\s*<br\s*/?>(.*?)</td>", block, re.S)
        status = re.search(r"status_(\d)\.gif", block)
        out.append({"id": int(m.group(1)), "price": int(re.sub(r"[.,]", "", price.group(1))) if price else None,
                    "place": clean(place.group(1)) if place else "", "vrsta": clean(kind.group(1)) if kind else "",
                    "title": clean(title.group(1)) if title else "", "snippet": clean(snippet.group(1))[:400] if snippet else "",
                    "agency_id": agency.group(1) if agency else "", "agency": clean(agency.group(2)) if agency else "",
                    "status": status.group(1) if status else ""})
    return out


def parse_detail(html):
    text = clean(html)
    area = re.search(r"Površina:\s*([\d.,]+)\s*m2", text)
    plot = re.search(r"Okućnica:\s*([\d.,]+)\s*m2", text)
    desc = re.search(r"OPIS OBJEKTA\s*Hrvatski English Deutsch Italiano Ruski\s*(.*?)(?:Interni broj|REC ID)", text)
    return {"area": parse_number(area.group(1)) if area else None, "plot": parse_number(plot.group(1)) if plot else None,
            "description": desc.group(1)[:3000] if desc else ""}


def seen_rows():
    rows = []
    for branch, name in (("state", "state.db"), ("state-redmi", "redmi.db")):
        path = OUT / name
        try:
            path.write_bytes(requests.get(f"{RAW}{branch}/{name}", timeout=60).content)
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            rows += [dict(r) for r in conn.execute(
                "SELECT key, source, kind, jls, price, area, title, settlement, first_seen, url FROM listings")]
            conn.close()
        except Exception as exc:  # noqa: BLE001
            print(name, exc)
        path.unlink(missing_ok=True)
    return rows


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    criteria = cfg["kriteriji"]
    locator = Locator()
    http = Http(delay=1.0)
    summary = {}
    try:
        # Nazivi mjesta kako ih vodi portal (listcity.asp), samo naša naselja.
        ours = {}
        for j in locator.jls.values():
            if j.included:
                for n in [j.name, *j.settlements]:
                    ours[fold(n)] = j.name
        cities = http.get(f"{RC}listcity.asp").text
        names = sorted(set(re.findall(r"list\.asp\?[^\"']*mjesto=([^&\"']+)", cities)))
        places = [n for n in names if fold(requests.utils.unquote(n).replace("+", " ")) in ours]
        summary["rc_places_total"] = len(names)
        summary["rc_places_ours"] = places
        if not places:      # rezerva: naši nazivi velikim slovima
            places = sorted({n.upper() for n in ours})
        items = {}
        for place in places:
            for vrsta, kind, cap in ((1, HOUSE, criteria["kuca"]["max_cijena"]), (3, LAND, criteria["zemljiste"]["max_cijena"])):
                for page in range(1, 5):
                    html = http.get(f"{RC}list.asp?vrsta={vrsta}&mjesto={place}&akcija=1&sort=objekt_id&smjer=desc"
                                    f"&cijenaDo={cap}&page={page}").text
                    rows = parse_list(html)
                    for r in rows:
                        r["kind"] = kind
                        items.setdefault(r["id"], r)
                    if len(rows) < 20:
                        break
        summary["rc_items"] = len(items)
        summary["rc_by_vrsta"] = Counter(r["vrsta"] for r in items.values())
        save("rc_items.json", list(items.values()))

        rows = seen_rows()
        seen = dedupe.Seen(locator)
        by_key = {}
        for r in rows:
            seen.add(dict(r))
            by_key[r["key"]] = r
        summary["seen_rows"] = len(rows)

        # Najnoviji prvi; stranica oglasa za površinu.
        results, per_agency, unmatched, matched = Counter(), defaultdict(Counter), [], []
        details = 0
        for r in sorted(items.values(), key=lambda r: -r["id"]):
            x = Listing("realestatecroatia", str(r["id"]), f"{RC}detail.asp?id={r['id']}", r["title"], r["kind"],
                        subtype=r["vrsta"], price=r["price"], location_text=r["place"],
                        settlement=re.sub(r"\s*\(.*\)$", "", r["place"]).title(), description=r["snippet"])
            d = evaluate(x, criteria, locator)
            if d.status == REJECT and not any("površin" in why or "nije navedena" in why for why in d.reasons):
                results["odbijen_bez_povrsine"] += 1
                continue
            if details >= MAX_DETAILS:
                results["nije_otvoren"] += 1
                continue
            details += 1
            try:
                info = parse_detail(http.get(x.url).text)
            except Exception:  # noqa: BLE001
                results["greska"] += 1
                continue
            x.area, x.plot_area = info["area"], info["plot"]
            x.description = info["description"] or x.description
            d = evaluate(x, criteria, locator)
            if d.status == REJECT:
                results["odbijen"] += 1
                continue
            twins = seen.twins(dedupe.row(x, d)) if x.price and x.area else []
            agency = r["agency"] or "?"
            item = {"id": r["id"], "url": x.url, "agency": agency, "kind": r["kind"], "place": r["place"], "jls": d.jls,
                    "price": x.price, "area": x.area, "title": r["title"][:120]}
            if twins:
                results["vec_imamo"] += 1
                per_agency[agency]["vec_imamo"] += 1
                item["twins"] = [(t["key"], by_key.get(t["key"], {}).get("first_seen")) for t in twins[:3]]
                matched.append(item)
            else:
                results["nemamo"] += 1
                per_agency[agency]["nemamo"] += 1
                unmatched.append(item)
        summary["rc_results"] = dict(results)
        summary["rc_per_agency"] = {a: dict(c) for a, c in sorted(per_agency.items(), key=lambda kv: -sum(kv[1].values()))}
        summary["rc_id_range"] = [min(items), max(items)] if items else None
        save("rc_unmatched.json", unmatched)
        save("rc_matched.json", matched)
    except Exception:  # noqa: BLE001
        summary["rc_error"] = traceback.format_exc()[-2000:]
    save("sazetak.json", summary)

    # Nova stranica realestatecroatia.hr
    try:
        r = http.get("https://realestatecroatia.hr/hr/lista/primorsko-goranska/")
        save("rec_hr_lista.html", r.text[:500000])
        summary["rec_hr"] = {"status": r.status_code, "bytes": len(r.text), "next_data": "__NEXT_DATA__" in r.text,
                             "nuxt": "__NUXT__" in r.text, "api_hints": sorted(set(re.findall(r"https?://[^\"' ]*api[^\"' ]*", r.text)))[:10]}
    except Exception as exc:  # noqa: BLE001
        summary["rec_hr"] = str(exc)[:300]
    save("sazetak.json", summary)


if __name__ == "__main__":
    main()
