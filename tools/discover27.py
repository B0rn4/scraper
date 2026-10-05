"""Dvadeset sedmi krug (faza 5, agencije):
1. nekretnine.hr: oglašivači (agencije) oglasa kuća i zemljišta u našim gradovima i
   općinama – koliko oglasa imaju i koliko ih prolazi naše kriterije.
2. index.hr: koja polja oglasa opisuju oglašivača.
3. Web stranice najaktivnijih agencija: WordPress (wp-json, vrste objava za
   nekretnine), RSS, sitemap s datumima izmjene."""

import json
import re
import sys
import time
import traceback
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urljoin, urlparse

from curl_cffi import requests as cffi

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.filters import evaluate  # noqa: E402
from scraper.http import Http  # noqa: E402
from scraper.locations import Locator  # noqa: E402
from scraper.models import REJECT  # noqa: E402
from scraper.runner import load_config  # noqa: E402
from scraper.sources.index_oglasi import IndexOglasi  # noqa: E402
from scraper.sources.nekretnine_hr import BASE, CATEGORIES, _NEXT_DATA, _listing, jls_slug  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "debug-out") / "discovery27"
SKIP_HOSTS = re.compile(r"nekretnine\.hr|indomio|crozilla|facebook|instagram|linkedin|youtube|google|apple|twitter|x\.com"
                        r"|tiktok|pinterest|whatsapp|viber|mailto|tel:|immobiliare|getrix|cookiebot|onetrust", re.I)


def save(name, data):
    (OUT / name).write_text(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=1, default=str),
                            encoding="utf-8")


def results_of(html):
    m = _NEXT_DATA.search(html)
    if not m:
        return [], 1
    props = json.loads(m.group(1))["props"]["pageProps"]
    for query in props.get("dehydratedState", {}).get("queries", []):
        data = query.get("state", {}).get("data")
        if isinstance(data, dict) and isinstance(data.get("results"), list):
            return data["results"], int(data.get("maxPages") or 1)
    return [], 1


def agency_of(result):
    adv = (result.get("realEstate") or {}).get("advertiser") or result.get("advertiser") or {}
    agency = adv.get("agency") or {}
    name = agency.get("displayName") or agency.get("label") or (adv.get("supervisor") or {}).get("displayName") or ""
    return str(agency.get("id") or name or "privatno"), name or "privatno", adv


def nekretnine_part(http, locator, criteria, summary):
    stats = defaultdict(lambda: {"name": "", "all": 0, "pass": 0, "by_kind": Counter(), "jls": Counter(), "advertiser": None})
    raw_saved = False
    for jls in [j.name for j in locator.jls.values() if j.included]:
        for category, kind, _ in CATEGORIES:
            url = f"{BASE}/{category}/{jls_slug(jls)}/"
            for page in range(1, 41):
                try:
                    html = http.get(f"{url}?criterio=data&ordine=desc&pag={page}").text
                except Exception as exc:  # noqa: BLE001
                    summary.setdefault("nekretnine_errors", []).append(f"{url} {page}: {exc}"[:200])
                    break
                results, pages = results_of(html)
                if not raw_saved and results:
                    save("nekretnine_result_sample.json", results[0])
                    raw_saved = True
                for r in results:
                    if not r.get("realEstate"):
                        continue
                    key, name, adv = agency_of(r)
                    item = stats[key]
                    item["name"] = name
                    item["advertiser"] = item["advertiser"] or adv
                    item["all"] += 1
                    item["by_kind"][kind] += 1
                    x = _listing(r, kind)
                    d = evaluate(x, criteria, locator)
                    item["jls"][d.jls or jls] += 1
                    if d.status != REJECT:
                        item["pass"] += 1
                if page >= pages:
                    break
    ranked = sorted(stats.items(), key=lambda kv: (-kv[1]["pass"], -kv[1]["all"]))
    summary["nekretnine_agencies"] = [
        {"id": k, "name": v["name"], "all": v["all"], "pass": v["pass"], "by_kind": dict(v["by_kind"]),
         "jls": dict(v["jls"].most_common(6))} for k, v in ranked[:60]]
    summary["nekretnine_total"] = {"listings": sum(v["all"] for v in stats.values()),
                                   "pass": sum(v["pass"] for v in stats.values()), "advertisers": len(stats)}
    save("nekretnine_advertisers_top.json", [{"id": k, "advertiser": v["advertiser"]} for k, v in ranked[:30]])
    return ranked


def agency_sites(http, ranked, summary):
    """Vanjske poveznice sa stranice agencije na nekretnine.hr (web stranica agencije)."""
    sites = {}
    for key, v in ranked[:30]:
        adv = v["advertiser"] or {}
        agency = adv.get("agency") or {}
        page = agency.get("agencyUrl") or agency.get("url") or agency.get("link") or ""
        found = []
        for field in ("website", "webSite", "siteUrl", "homepage", "web"):
            if agency.get(field):
                found.append(agency[field])
        if page and not found:
            try:
                html = http.get(urljoin(BASE, page)).text
                for href in re.findall(r'href="(https?://[^"]+)"', html):
                    if not SKIP_HOSTS.search(href):
                        found.append(href)
            except Exception as exc:  # noqa: BLE001
                found.append(f"greška: {exc}"[:150])
        sites[v["name"]] = {"page": page, "links": list(dict.fromkeys(found))[:8], "pass": v["pass"], "all": v["all"]}
    summary["agency_sites"] = sites
    return sites


def probe_site(s, url):
    res = {"url": url}
    try:
        r = s.get(url, timeout=30)
        html = r.text
        res.update(status=r.status_code, final=str(r.url), bytes=len(html))
        res["generator"] = (re.search(r'<meta name="generator" content="([^"]+)"', html, re.I) or [None, None])[1]
        res["wp"] = "wp-content" in html or "wp-json" in html
        res["feeds"] = re.findall(r'<link[^>]+type="application/(?:rss|atom)\+xml"[^>]+href="([^"]+)"', html, re.I)[:4]
        res["hints"] = sorted(set(re.findall(r"houzez|realhomes|wpresidence|estatik|easy-property|propertyhive|"
                                             r"realestate|nekretnine-cms|agentis|immo|realia|realsys|kuca\.hr|nekretnine365",
                                             html, re.I)))[:8]
        root = f"{urlparse(str(r.url)).scheme}://{urlparse(str(r.url)).netloc}/"
        if res["wp"]:
            try:
                api = s.get(root + "wp-json/", timeout=30).json()
                res["wp_routes"] = [k for k in (api.get("routes") or {}) if re.search(r"propert|nekretn|estate|listing|oglas", k)][:10]
            except Exception as exc:  # noqa: BLE001
                res["wp_routes"] = f"greška: {exc}"[:120]
        for sm in ("sitemap_index.xml", "sitemap.xml", "wp-sitemap.xml"):
            try:
                x = s.get(root + sm, timeout=30)
                if x.status_code == 200 and "<" in x.text[:200]:
                    locs = re.findall(r"<loc>([^<]+)</loc>", x.text)
                    res["sitemap"] = {"file": sm, "n": len(locs), "sample": locs[:12],
                                      "lastmod": re.findall(r"<lastmod>([^<]+)</lastmod>", x.text)[:5]}
                    break
            except Exception:  # noqa: BLE001
                continue
    except Exception as exc:  # noqa: BLE001
        res["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    return res


def index_part(locator, criteria, summary):
    src = IndexOglasi(Http(delay=1.5), locator, criteria)
    data = src._api("houses-for-sale", 1)
    items = data.get("data") or []
    if items:
        save("index_item_sample.json", items[0])
        single = src.http.get(f"https://www.index.hr/oglasi/api/aditem/single-ad?code={items[0].get('code')}&format=1",
                              headers={"Accept": "application/json"}).json()
        save("index_single_sample.json", single)
    keys = Counter()
    for x in items:
        for k, v in x.items():
            if re.search(r"agen|user|company|advert|owner|seller|publisher|client", k, re.I):
                keys[f"{k}={json.dumps(v, ensure_ascii=False)[:80]}"] += 1
    summary["index_advertiser_fields"] = keys.most_common(40)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    locator = Locator()
    http = Http(delay=1.0)
    summary = {}
    ranked = []
    try:
        ranked = nekretnine_part(http, locator, cfg["kriteriji"], summary)
    except Exception:  # noqa: BLE001
        summary["nekretnine_error"] = traceback.format_exc()[-1500:]
    save("sazetak.json", summary)
    try:
        sites = agency_sites(http, ranked, summary)
        s = cffi.Session(impersonate="chrome")
        probes = {}
        for name, item in sites.items():
            for link in item["links"][:2]:
                if link.startswith("http"):
                    probes.setdefault(name, []).append(probe_site(s, link))
                    time.sleep(1)
        summary["site_probes"] = probes
    except Exception:  # noqa: BLE001
        summary["sites_error"] = traceback.format_exc()[-1500:]
    save("sazetak.json", summary)
    try:
        index_part(locator, cfg["kriteriji"], summary)
    except Exception:  # noqa: BLE001
        summary["index_error"] = traceback.format_exc()[-1500:]
    save("sazetak.json", summary)


if __name__ == "__main__":
    main()
