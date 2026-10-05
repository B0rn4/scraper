"""Dvadeset osmi krug:
1. realestatecroatia.com (Labin d.o.o., sustav Agentor koji koriste mnoge agencije):
   oglasi kuća i zemljišta u našim gradovima i općinama, koliko ih prolazi kriterije,
   koliko ih već imamo s naših portala (state.db, redmi.db) i datumi objave.
2. Web stranice najaktivnijih agencija: koji sustav koriste (Agentor?), sitemap, RSS.
3. Natječaji: stranice Rijeke (raspolaganje zemljištem), Opatije (prodaja nekretnina),
   Lovrana; poveznice s objava Matulja i Crikvenice bez teksta; puni tekstovi natječaja
   (za testove pravila)."""

import json
import re
import sqlite3
import sys
import time
import traceback
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from curl_cffi import requests as cffi

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper import dedupe, tenders  # noqa: E402
from scraper.filters import evaluate  # noqa: E402
from scraper.http import Http  # noqa: E402
from scraper.locations import Locator  # noqa: E402
from scraper.models import HOUSE, LAND, REJECT, Listing  # noqa: E402
from scraper.runner import load_config  # noqa: E402
from scraper.text import fold, parse_number  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "debug-out") / "discovery28"
RC = "https://www.realestatecroatia.com/hrv/"
RAW = "https://raw.githubusercontent.com/B0rn4/scraper/"
AGENCIES = {
    "Dogma": "https://dogma-nekretnine.com/", "RE/MAX Centar": "https://www.remax-centarnekretnina.com/home",
    "DUX": "https://www.dux-nekretnine.hr/", "Euro Immobilien": "https://euro-immobilien.biz/",
    "Miro": "https://mironekretnine.hr/", "Pontera": "https://pontera.hr/", "Manor": "https://manor.hr/home",
    "Premium SM": "https://premium-nekretnine.com/", "Vero Krk": "https://vero-krk.hr/",
    "Smart Invest": "https://www.smart-invest.hr/", "Kaiser": "https://www.kaiser-immobilien.hr/",
}
TENDER_PAGES = {
    "Rijeka zemljište": "https://www.rijeka.hr/gradska-uprava/natjecaji-2/raspolaganje-zemljistem-prodaja-pravo-gradenja-sluznosti-i-zakup/",
    "Rijeka stanovi i poslovni": "https://www.rijeka.hr/gradska-uprava/natjecaji-2/natjecaji-za-prodaju-stanova-poslovnih-prostora/",
    "Opatija prodaja nekretnina": "https://opatija.hr/transparentnost/natjecaji/prodaja-nekretnina/",
    "Lovran natječaji": "https://lovran.hr/natjecaji-i-javni-pozivi/",
    "Matulji objava": "https://matulji.hr/portal/javni-natjecaj-za-prodaju-nekretnina-u-vlasnistvu-opcine-matulji-2-2/",
    "Crikvenica objava 5": "https://www.crikvenica.hr/natjecaj-za-prodaju-gradevinskog-zemljista-u-vlasnistvu-grada-crikvenice-5/",
}


def save(name, data):
    (OUT / name).write_text(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=1, default=str),
                            encoding="utf-8")


def clean(html):
    return " ".join(re.sub(r"<[^>]+>", " ", html or "").split())


def anchors(html, base):
    out = []
    for href, inner in re.findall(r"""<a[^>]+href=["']([^"'#]+)["'][^>]*>(.*?)</a>""", html, re.S | re.I):
        out.append((clean(inner)[:160], urljoin(base, href)))
    return out


# --- 1. realestatecroatia.com -------------------------------------------------

def rc_items(html):
    """Oglasi s popisa: id, naslov/tekst bloka, cijena, površina (grubo, za procjenu)."""
    items = {}
    for m in re.finditer(r'detail\.asp\?id=(\d+)', html):
        rid = m.group(1)
        if rid in items:
            continue
        block = clean(html[max(0, m.start() - 1500):m.start() + 1500])
        items[rid] = block
    return items


def seen_rows():
    rows = []
    for branch, name in (("state", "state.db"), ("state-redmi", "redmi.db")):
        try:
            path = OUT / name
            path.write_bytes(requests.get(f"{RAW}{branch}/{name}", timeout=60).content)
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            rows += [dict(r) for r in conn.execute(
                "SELECT key, source, kind, jls, price, area, title, settlement, first_seen FROM listings")]
            conn.close()
            path.unlink()
        except Exception as exc:  # noqa: BLE001
            print(name, exc)
    return rows


def rc_part(summary, locator, criteria):
    http = Http(delay=1.5)
    probe = {}
    # Parametri popisa: vrsta 1 kuće, 3 zemljišta; akcija 1 prodaja; sortiranje.
    for name, url in (("mjesto", f"{RC}list.asp?vrsta=1&mjesto=MALINSKA&akcija=1"),
                      ("mjesto_sort_datum", f"{RC}list.asp?vrsta=1&mjesto=MALINSKA&akcija=1&sort=datum&smjer=desc"),
                      ("mjesto_sort_id", f"{RC}list.asp?vrsta=1&mjesto=MALINSKA&akcija=1&sort=id&smjer=desc"),
                      ("opcina", f"{RC}listunique.asp?opcina=malinska-dubasnica"),
                      ("zemljiste", f"{RC}list.asp?vrsta=3&mjesto=MALINSKA&akcija=1")):
        try:
            r = http.get(url)
            items = rc_items(r.text)
            probe[name] = {"status": r.status_code, "bytes": len(r.text), "n": len(items), "ids": list(items)[:12],
                           "pages": sorted(set(re.findall(r"[?&]page=(\d+)", r.text)), key=int)[-3:]}
            save(f"rc_{name}.html", r.text[:400000])
        except Exception as exc:  # noqa: BLE001
            probe[name] = str(exc)[:200]
    summary["rc_probe"] = probe
    first = next((v["ids"][0] for v in probe.values() if isinstance(v, dict) and v.get("ids")), None)
    if first:
        save("rc_detail.html", http.get(f"{RC}detail.asp?id={first}").text[:400000])

    # Svi oglasi kuća i zemljišta u našim gradovima/općinama (po mjestu = naziv grada/općine i naselja).
    rows = seen_rows()
    seen = dedupe.Seen(locator)
    first_seen = {}
    for r in rows:
        seen.add(dict(r))
        first_seen[r["key"]] = r.get("first_seen")
    summary["seen_rows"] = len(rows)
    places = []
    for j in locator.jls.values():
        if j.included:
            places += [j.name] + [s for s in j.settlements if s != j.name]
    found = {}
    for place in places[:400]:
        for vrsta, kind in ((1, HOUSE), (3, LAND)):
            for page in range(1, 6):
                try:
                    html = http.get(f"{RC}list.asp?vrsta={vrsta}&mjesto={fold(place).upper().replace(' ', '+')}"
                                    f"&akcija=1&page={page}").text
                except Exception:  # noqa: BLE001
                    break
                items = rc_items(html)
                new = {k: v for k, v in items.items() if k not in found}
                for rid, block in new.items():
                    found[rid] = {"kind": kind, "place": place, "block": block[:600]}
                if len(new) < 5:
                    break
    summary["rc_found"] = len(found)
    results, unmatched = Counter(), []
    for rid, item in found.items():
        block = item["block"]
        price = next((parse_number(p) for p in re.findall(r"(\d{1,3}(?:\.\d{3})+|\d{4,})\s*(?:€|EUR)", block)), None)
        area = next((parse_number(a) for a in re.findall(r"(\d+(?:[.,]\d+)?)\s*m(?:2|²)", block)), None)
        x = Listing("realestatecroatia", rid, f"{RC}detail.asp?id={rid}", block[:120], item["kind"], price=price,
                    area=area, settlement=item["place"], location_text=item["place"])
        d = evaluate(x, criteria, locator)
        if d.status == REJECT:
            results["odbijen"] += 1
            continue
        twins = seen.twins(dedupe.row(x, d)) if price and area else []
        if twins:
            results["vec_imamo"] += 1
        else:
            results["nemamo"] += 1
            unmatched.append({"id": rid, "kind": item["kind"], "place": item["place"], "price": price, "area": area,
                              "block": block[:300]})
    summary["rc_results"] = dict(results)
    summary["rc_unmatched_sample"] = unmatched[:40]
    # Datumi objave na stranici oglasa (za usporedbu s našim prvim viđenjem).
    dates = []
    for item in unmatched[:25]:
        try:
            html = http.get(f"{RC}detail.asp?id={item['id']}").text
            text = clean(html)
            m = re.search(r"(?i)(datum[^:]{0,30}:\s*[\d. /-]{8,12}|objavljeno[^:]{0,20}:?\s*[\d. /-]{8,12}|ažurirano[^:]{0,20}:?\s*[\d. /-]{8,12})", text)
            agency = re.search(r"showconn\.asp\?id=(\d+)", html)
            dates.append({"id": item["id"], "date": m.group(1) if m else "", "agency": agency.group(1) if agency else ""})
        except Exception as exc:  # noqa: BLE001
            dates.append({"id": item["id"], "error": str(exc)[:100]})
    summary["rc_detail_dates"] = dates


# --- 2. stranice agencija -----------------------------------------------------

def agency_part(summary):
    s = cffi.Session(impersonate="chrome")
    out = {}
    for name, url in AGENCIES.items():
        res = {"url": url}
        try:
            r = s.get(url, timeout=30)
            html = r.text
            res.update(status=r.status_code, final=str(r.url), bytes=len(html))
            res["generator"] = (re.search(r'<meta name="generator" content="([^"]+)"', html, re.I) or [None, None])[1]
            res["hints"] = sorted(set(m.lower() for m in re.findall(
                r"agentor|realestatecroatia|labin d\.o\.o|kuca\.hr|e-nekretnine|wp-content|houzez|next\.js|__NEXT_DATA__|"
                r"nuxt|drupal|joomla", html, re.I)))
            res["footer"] = clean(html[-4000:])[-400:]
            root = f"{urlparse(str(r.url)).scheme}://{urlparse(str(r.url)).netloc}/"
            res["listing_links"] = [a for a in anchors(html, root) if re.search(r"prodaja|kuc|zemlji|nekretnin|listing|lokacij", a[1], re.I)][:15]
            for sm in ("sitemap.xml", "sitemap_index.xml"):
                x = s.get(root + sm, timeout=30)
                if x.status_code == 200 and "<loc>" in x.text:
                    locs = re.findall(r"<loc>([^<]+)</loc>", x.text)
                    res["sitemap"] = {"file": sm, "n": len(locs), "sample": locs[:10],
                                      "lastmod": re.findall(r"<lastmod>([^<]+)</lastmod>", x.text)[:5]}
                    break
            save(f"agency_{fold(name).replace(' ', '_').replace('/', '')}.html", html[:300000])
        except Exception as exc:  # noqa: BLE001
            res["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        out[name] = res
        time.sleep(1)
    summary["agencies"] = out


# --- 3. natječaji -------------------------------------------------------------

def tender_part(summary, locator):
    http = Http(delay=1.5)
    pages = {}
    for name, url in TENDER_PAGES.items():
        try:
            r = http.get(url)
            links = [a for a in anchors(r.text, url) if re.search(r"natje|prodaj|\.pdf|\.docx?|preuzmi|ovdje|zemlji", f"{a[0]} {a[1]}", re.I)]
            pages[name] = {"status": r.status_code, "links": links[:60], "text": clean(re.sub(
                r"(?is)<(script|style|nav|header|footer)[^>]*>.*?</\1>", " ", r.text))[:4000]}
        except Exception as exc:  # noqa: BLE001
            pages[name] = str(exc)[:200]
    summary["tender_pages"] = pages
    reader = tenders.Reader(http, locator)
    texts = {}
    for site in tenders.load_sites():
        try:
            items = reader.fetch(site)
        except Exception as exc:  # noqa: BLE001
            texts[site["naziv"]] = str(exc)[:200]
            continue
        for t in items[:10]:
            try:
                reader.load_text(t)
                texts[t.url] = {"site": site["naziv"], "title": t.title, "published": t.published, "text": t.text[:30000]}
            except Exception as exc:  # noqa: BLE001
                texts[t.url] = str(exc)[:200]
    save("natjecaji_tekstovi.json", texts)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    locator = Locator()
    summary = {}
    for name, step in (("tenders", lambda: tender_part(summary, locator)),
                       ("agencies", lambda: agency_part(summary)),
                       ("rc", lambda: rc_part(summary, locator, cfg["kriteriji"]))):
        try:
            step()
        except Exception:  # noqa: BLE001
            summary[f"{name}_error"] = traceback.format_exc()[-1500:]
        save("sazetak.json", summary)


if __name__ == "__main__":
    main()
