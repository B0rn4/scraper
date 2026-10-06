"""Trideset četvrti krug: mali oglasi Novog lista – Butiga (butiga.hr, Novi list + Glas
Istre), oglasnik Glasa Istre, burza.com.hr (Kvarner i Istra). Struktura stranica,
kategorije nekretnina, broj oglasa kuća/zemljišta, uzorci i oglasi s našeg područja."""

import json
import re
import sys
import time
import traceback
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin, urlparse

from curl_cffi import requests as cffi

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.locations import Locator  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "debug-out") / "discovery34"
START = {
    "butiga": "https://www.butiga.hr/",
    "glasistre_oglasi": "https://oglasni.glasistre.hr/",
    "novilist": "https://www.novilist.hr/",
    "burza_kuce": "https://burza.com.hr/oglasi/nekretnine-kuce-prodaja/kvarner-i-istra",
    "burza_nekretnine_rijeka": "https://burza.com.hr/oglasi/nekretnine/kvarner-i-istra-rijeka",
}
LINK = re.compile(r"nekretnin|kuć|kuc|zemlji|prodaj|oglas|butiga|kategorij|category|real", re.I)


def clean(html):
    return " ".join(re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html or "")).split())


def save(name, text):
    (OUT / name).write_text(text if isinstance(text, str) else json.dumps(text, ensure_ascii=False, indent=1), encoding="utf-8")


def links_of(html, base, same_host=True):
    out = []
    for href, inner in re.findall(r"""<a[^>]+href=["']([^"'#]+)["'][^>]*>(.*?)</a>""", html, re.S | re.I):
        full = urljoin(base, href)
        if same_host and urlparse(full).netloc != urlparse(base).netloc:
            continue
        label = clean(inner)[:100]
        if LINK.search(label) or LINK.search(href):
            out.append((label, full))
    return list(dict.fromkeys(out))


def probe(s, locator, name, url):
    r = s.get(url, timeout=40)
    html = r.text
    text = clean(html)
    res = {"url": url, "status": r.status_code, "final": str(r.url), "bytes": len(html),
           "cloudflare": "Just a moment" in html[:3000], "title": (re.search(r"<title>(.*?)</title>", html, re.S) or [0, ""])[1][:150],
           "generator": (re.search(r'<meta name="generator" content="([^"]+)"', html, re.I) or [None, None])[1],
           "hints": sorted(set(re.findall(r"wp-json|__NEXT_DATA__|__NUXT__|/api/[\w/-]+|application/ld\+json", html)))[:10],
           "links": links_of(html, str(r.url))[:80],
           "places": dict(Counter(j.name for j, _ in locator.scan_text(text) if j.included)),
           "text_start": text[:1500]}
    save(f"{name}.html", html[:600000])
    return res


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    s = cffi.Session(impersonate="chrome")
    locator = Locator()
    summary = {}
    for name, url in START.items():
        try:
            summary[name] = probe(s, locator, name, url)
        except Exception:  # noqa: BLE001
            summary[name] = {"url": url, "error": traceback.format_exc()[-600:]}
        time.sleep(1)
        save("sazetak.json", summary)
    # Druga razina: poveznice na nekretnine (kuće, zemljišta) na Butigi i oglasniku Glasa Istre.
    second = {}
    for name in ("butiga", "glasistre_oglasi", "novilist"):
        for label, link in (summary.get(name, {}).get("links") or []):
            if not re.search(r"nekretnin|kuć|kuc|zemlji|butiga|mali.oglas", f"{label} {link}", re.I) or link in second:
                continue
            if len(second) >= 25:
                break
            try:
                r = s.get(link, timeout=40)
                text = clean(r.text)
                second[link] = {"from": name, "label": label, "status": r.status_code, "bytes": len(r.text),
                                "places": dict(Counter(j.name for j, _ in locator.scan_text(text) if j.included)),
                                "eur": len(re.findall(r"€|EUR|eura", text)), "m2": len(re.findall(r"m2|m²", text)),
                                "links": links_of(r.text, str(r.url))[:40], "text": text[:2500]}
                save(f"second_{len(second)}.html", r.text[:400000])
            except Exception as exc:  # noqa: BLE001
                second[link] = {"from": name, "error": str(exc)[:200]}
            time.sleep(1)
    save("druga_razina.json", second)


if __name__ == "__main__":
    main()
