"""Trideset drugi krug: banke, leasing kuće i agencije za naplatu potraživanja – gdje
objavljuju prodaju preuzetih nekretnina, kako se stranice čitaju i ima li nekretnina na
našem području (kuće, zemljišta)."""

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

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "debug-out") / "discovery32"
SITES = {
    # banke
    "Addiko": "https://www.addiko.hr/prodaja-nekretnina/",
    "HPB nekretnine": "https://www.hpb-nekretnine.hr/",
    "OTP banka – javni natječaji": "https://www.otpbanka.hr/javni-natjecaji",
    "Zaba – javni poziv": "https://www.zaba.hr/home/o-nama/javni-poziv",
    "PBZ nekretnine": "https://www.pbz-nekretnine.hr/",
    "Erste nekretnine": "https://www.erstenekretnine.hr/nekretnine",
    "OTP nekretnine": "https://www.otpnekretnine.hr/",
    "RBA": "https://www.rba.hr/",
    "Partner banka (PABA)": "https://e.paba.hr/pabanekretnine/",
    "Croatia banka": "https://www.croatiabanka.hr/info-centar/prodaja-nekretnina/stambene-nekretnine/",
    "HBOR": "https://www.hbor.hr/prodaja-nekretnina",
    "Istarska kreditna banka": "https://www.ikb.hr/",
    "Agram banka": "https://www.agrambanka.hr/",
    # leasing
    "Raiffeisen Leasing": "https://www.raiffeisen-leasing.hr/akcije-i-posebni-uvjeti/prodaja-nekretnina",
    "Erste S-Leasing": "https://www.s-leasing.hr/",
    "UniCredit Leasing": "https://unicreditleasing.hr/",
    "OTP Leasing": "https://www.otpleasing.hr/",
    "PBZ Leasing": "https://www.pbz-leasing.hr/",
    # naplata potraživanja
    "EOS Matrix nekretnine": "https://eosmatrix-nekretnine.com/real-estate/houses",
    "EOS Matrix zemljišta": "https://eosmatrix-nekretnine.com/real-estate/land",
    "APS Croatia": "http://www.apscroatia.com/index.php?ln=1",
    "B2 Kapital": "https://www.b2kapital.hr/",
}
LINK = re.compile(r"nekretnin|prodaj|imovin|kuć|kuc|zemlji|natječ|natjec|javni[- ]poziv|real-estate|propert|ponud|oglas", re.I)


def clean(html):
    return " ".join(re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html or "")).split())


def probe(s, locator, name, url):
    res = {"url": url}
    r = s.get(url, timeout=40)
    html = r.text
    res.update(status=r.status_code, final=str(r.url), bytes=len(html))
    res["cloudflare"] = "Just a moment" in html[:3000]
    text = clean(html)
    res["text_start"] = text[:600]
    root = f"{urlparse(str(r.url)).scheme}://{urlparse(str(r.url)).netloc}/"
    links = []
    for href, inner in re.findall(r"""<a[^>]+href=["']([^"'#]+)["'][^>]*>(.*?)</a>""", html, re.S | re.I):
        label = clean(inner)[:120]
        full = urljoin(str(r.url), href)
        if (LINK.search(label) or LINK.search(href)) and urlparse(full).netloc == urlparse(root).netloc:
            links.append((label, full))
    res["links"] = list(dict.fromkeys(links))[:50]
    places = Counter(j.name for j, _ in locator.scan_text(text) if j.included)
    res["our_places"] = dict(places)
    res["pdf"] = sorted(set(re.findall(r'href="([^"]+\.pdf)"', html, re.I)))[:15]
    res["json_hints"] = sorted(set(re.findall(r"(wp-json|__NEXT_DATA__|__NUXT__|api/[\w/-]+)", html)))[:10]
    (OUT / f"{re.sub(r'[^a-z0-9]+', '_', name.lower())}.html").write_text(html[:400000], encoding="utf-8")
    return res


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    s = cffi.Session(impersonate="chrome")
    locator = Locator()
    summary = {}
    for name, url in SITES.items():
        try:
            summary[name] = probe(s, locator, name, url)
        except Exception:  # noqa: BLE001
            summary[name] = {"url": url, "error": traceback.format_exc()[-600:]}
        time.sleep(1)
        (OUT / "sazetak.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    # Druga razina: poveznice s riječima nekretnina/prodaja na stranicama banaka i leasinga.
    second = {}
    for name, item in summary.items():
        for label, link in (item.get("links") or [])[:6]:
            if re.search(r"prodaj|nekretnin|imovin|real-estate|natječ|natjec|javni", f"{label} {link}", re.I) and link not in second:
                try:
                    r = s.get(link, timeout=40)
                    text = clean(r.text)
                    second[link] = {"from": name, "label": label, "status": r.status_code,
                                    "our_places": dict(Counter(j.name for j, _ in locator.scan_text(text) if j.included)),
                                    "kuca": len(re.findall(r"\bkuć", text, re.I)), "zemljiste": len(re.findall(r"zemljiš", text, re.I)),
                                    "text": text[:1500]}
                except Exception as exc:  # noqa: BLE001
                    second[link] = {"from": name, "error": str(exc)[:200]}
                time.sleep(1)
    (OUT / "druga_razina.json").write_text(json.dumps(second, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
