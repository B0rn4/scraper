"""Faza 0: provjera koji izvori su dostupni s GitHub Actions poslužitelja.

Za svaki URL bilježi status, veličinu, znakove zaštite od botova i strukturu
stranice, te sprema sažeti HTML u probe/results/samples/ za izradu parsera.
"""

import gzip
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

try:
    from curl_cffi import requests as cffi_requests
except ImportError:
    cffi_requests = None

OUT = Path(__file__).parent / "results"
SAMPLES = OUT / "samples"
MAX_SAVE = 5_000_000

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "hr-HR,hr;q=0.9,en;q=0.8",
}

PORTALS = {
    "njuskalo": ["https://www.njuskalo.hr/", "https://www.njuskalo.hr/prodaja-kuca/primorsko-goranska"],
    "oglasnik": ["https://www.oglasnik.hr/"],
    "index_oglasi": ["https://www.index.hr/oglasi/"],
    "nekretnine_hr": ["https://www.nekretnine.hr/"],
    "crozilla": ["https://www.crozilla.com/", "https://www.crozilla.com/prodaja-kuca/primorsko-goranska/"],
    "indomio": ["https://www.indomio.hr/", "https://www.indomio.hr/prodaja-kuca/primorsko-goranska/"],
    "gohome": ["https://www.gohome.hr/"],
    "trazimstan": ["https://www.trazimstan.hr/"],
    "realitica": ["https://www.realitica.com/"],
    "vender": ["https://www.vender.hr/"],
    "oglasi_hr": ["https://www.oglasi.hr/"],
    "nekretnine24": ["https://www.nekretnine24.hr/"],
    "ekvadrat": ["https://www.ekvadrat.hr/"],
}

FINA = {
    "fina_ocevidnik": ["https://ponip.fina.hr/ocevidnik-web/pocetna"],
    "fina_datagov": [
        "https://data.gov.hr/ckan/api/3/action/package_show?id=ocevidnik-nekretnina-i-pokretnina"
    ],
}

MUNICIPALITIES = {
    "baska": "baska.hr",
    "dobrinj": "dobrinj.hr",
    "kostrena": "kostrena.hr",
    "lovran": "lovran.hr",
    "malinska": "malinska.hr",
    "moscenicka_draga": "moscenicka-draga.hr",
    "omisalj": "omisalj.hr",
    "punat": "punat.hr",
    "vrbnik": "opcina-vrbnik.hr",
    "crikvenica": "crikvenica.hr",
    "kraljevica": "kraljevica.hr",
    "krk": "grad-krk.hr",
    "novi_vinodolski": "novi-vinodolski.hr",
    "opatija": "opatija.hr",
    "rijeka": "rijeka.hr",
}

OTHER = {
    "pgz": ["https://www.pgz.hr/"],
    "mpgi": ["https://mpgi.gov.hr/"],
    "cerp": ["https://www.cerp.hr/"],
    "novilist": ["https://www.novilist.hr/"],
}

BOT_MARKERS = {
    "cloudflare": ["just a moment", "cf-chl", "challenge-platform", "cf_chl_opt"],
    "radware": ["perfdrive", "shieldsquare", "radware"],
    "datadome": ["datadome"],
    "imperva": ["incapsula", "request unsuccessful", "_incap_"],
    "captcha": ["captcha"],
    "access_denied": ["access denied", "forbidden"],
}


def analyse(body: str) -> dict:
    low = body.lower()
    title = re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I)
    generator = re.search(r'<meta[^>]+name="generator"[^>]+content="([^"]+)"', body, re.I)
    feeds = re.findall(
        r'<link[^>]+type="application/(?:rss|atom)\+xml"[^>]+href="([^"]+)"', body, re.I
    )
    return {
        "title": (title.group(1).strip()[:120] if title else ""),
        "generator": generator.group(1) if generator else "",
        "bot_markers": [k for k, words in BOT_MARKERS.items() if any(w in low for w in words)],
        "next_data": "__NEXT_DATA__" in body,
        "nuxt": "__NUXT__" in body,
        "json_ld": low.count("application/ld+json"),
        "euro_mentions": body.count("€") + body.count("EUR"),
        "links": low.count("<a "),
        "feeds": feeds[:5],
    }


def fetch(session_get, url: str) -> dict:
    started = time.monotonic()
    try:
        resp = session_get(url, headers=HEADERS, timeout=30, allow_redirects=True)
        body = resp.text or ""
        return {
            "status": resp.status_code,
            "final_url": str(resp.url),
            "bytes": len(resp.content or b""),
            "content_type": resp.headers.get("content-type", ""),
            "seconds": round(time.monotonic() - started, 1),
            "body": body,
        }
    except Exception as exc:  # noqa: BLE001 – bilježimo svaku grešku
        return {
            "status": None,
            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
            "seconds": round(time.monotonic() - started, 1),
            "body": "",
        }


def probe(name: str, url: str, save: bool) -> dict:
    result = fetch(requests.get, url)
    blocked = result["status"] != 200 or analyse(result["body"])["bot_markers"]
    if blocked and cffi_requests is not None:
        alt = fetch(lambda u, **kw: cffi_requests.get(u, impersonate="chrome", **kw), url)
        result["impersonated"] = {k: v for k, v in alt.items() if k != "body"}
        if alt["status"] == 200 and result["status"] != 200:
            result["body_from"] = "impersonated"
            result["body"] = alt["body"]
    body = result.pop("body")
    result["analysis"] = analyse(body) if body else None
    if save and body:
        slug = re.sub(r"[^a-z0-9]+", "_", url.lower().split("//", 1)[-1]).strip("_")[:80]
        path = SAMPLES / f"{name}__{slug}.html.gz"
        path.write_bytes(gzip.compress(body[:MAX_SAVE].encode("utf-8", "replace")))
        result["sample"] = str(path.relative_to(OUT))
    result.update(name=name, url=url)
    return result


def robots_url(url: str) -> str:
    scheme, rest = url.split("//", 1)
    return f"{scheme}//{rest.split('/', 1)[0]}/robots.txt"


def main() -> None:
    SAMPLES.mkdir(parents=True, exist_ok=True)
    results = []

    try:
        egress = requests.get("https://ipinfo.io/json", timeout=15).json()
        egress = {k: egress.get(k) for k in ("country", "region", "city", "org")}
    except Exception as exc:  # noqa: BLE001
        egress = {"error": str(exc)}

    groups = [("portal", PORTALS, True), ("fina", FINA, True), ("other", OTHER, True)]
    for group, targets, save in groups:
        for name, urls in targets.items():
            for url in urls:
                results.append({"group": group, **probe(name, url, save)})
                time.sleep(2)
            if group == "portal":
                results.append({"group": "robots", **probe(name, robots_url(urls[0]), True)})
                time.sleep(2)

    for name, domain in MUNICIPALITIES.items():
        home = probe(name, f"https://{domain}/", True)
        results.append({"group": "municipality", **home})
        base = home.get("final_url") or f"https://{domain}/"
        base = base if base.endswith("/") else base + "/"
        results.append({"group": "municipality_feed", **probe(name, base + "feed/", True)})
        time.sleep(2)

    (OUT / "results.json").write_text(
        json.dumps({"egress": egress, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# Rezultati testa izvedivosti",
        "",
        f"Vrijeme: {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC  ",
        f"Izlazna IP adresa: {egress}",
        "",
        "| grupa | izvor | URL | status | KB | s | zaštita | naslov |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        a = r.get("analysis") or {}
        status = r.get("status") or r.get("error", "")
        imp = r.get("impersonated")
        if imp:
            status = f"{status} / imp {imp.get('status') or imp.get('error', '')}"
        lines.append(
            "| {g} | {n} | {u} | {s} | {kb} | {t} | {b} | {ti} |".format(
                g=r["group"],
                n=r["name"],
                u=r["url"],
                s=str(status).replace("|", "/"),
                kb=round((r.get("bytes") or 0) / 1024),
                t=r.get("seconds"),
                b=",".join(a.get("bot_markers", [])),
                ti=a.get("title", "").replace("|", "/"),
            )
        )
    (OUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
