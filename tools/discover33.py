"""Trideset treći krug: puni sadržaj stranica banaka koje spominju naše područje (HBOR
nekretnine, Croatia banka – zemljišta i natječaji), OTP nekretnine (filtar županije),
PBZ nekretnine (kuće i zemljišta)."""

import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

from curl_cffi import requests as cffi

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.locations import Locator  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "debug-out") / "discovery33"
PAGES = {
    "HBOR nekretnine": "https://www.hbor.hr/hbor-nekretnine/66",
    "HBOR natječaj": "https://www.hbor.hr/javni-natjecaj-za-prikupljanje-ponuda-za-kupnju-nekretnina-u-vlasnistvu-hbor-a/2",
    "Croatia banka zemljišta": "https://www.croatiabanka.hr/info-centar/prodaja-nekretnina/zemljista/",
    "Croatia banka natječaji": "https://www.croatiabanka.hr/info-centar/prodaja-nekretnina/natjecaji/",
    "Croatia banka stambene": "https://www.croatiabanka.hr/info-centar/prodaja-nekretnina/stambene-nekretnine/",
    "Croatia banka stambeno-poslovne": "https://www.croatiabanka.hr/info-centar/prodaja-nekretnina/stambenoposlovne-nekretnine/",
    "OTP nekretnine prodaja": "https://www.otpnekretnine.hr/search/prodaja/",
    "OTP nekretnine dražbe": "https://www.otpnekretnine.hr/search/drazbe/",
    "PBZ nekretnine kuće": "https://www.pbz-nekretnine.hr/prodaja-kuca",
    "PBZ nekretnine zemljišta": "https://www.pbz-nekretnine.hr/prodaja-zemljista",
    "PBZ nekretnine natječaji": "https://www.pbz-nekretnine.hr/natjecaji",
    "OTP banka javni natječaji": "https://www.otpbanka.hr/javni-natjecaji-otp-banke",
}


def clean(html):
    return " ".join(re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html or "")).split())


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    s = cffi.Session(impersonate="chrome")
    locator = Locator()
    out = {}
    for name, url in PAGES.items():
        try:
            r = s.get(url, timeout=40)
            text = clean(r.text)
            places = {}
            for j, found in locator.scan_text(text):
                if j.included:
                    places.setdefault(j.name, []).append(found)
            snippets = []
            for m in re.finditer(r"Dobrinj|Malinsk|Krk|Rijek|Opatij|Crikvenic|Kostren|Omišalj|Njivic|Punat|Bašk|Vrbnik|Lovran|Kraljevic|Matulj",
                                 text):
                snippets.append(text[max(0, m.start() - 250):m.start() + 350])
            links = [(clean(t)[:100], urljoin(url, h)) for h, t in
                     re.findall(r"""<a[^>]+href=["']([^"'#]+)["'][^>]*>(.*?)</a>""", r.text, re.S | re.I)
                     if re.search(r"nekretnin|prodaj|natje|\.pdf|single|search|zupanij", h + t, re.I)]
            scripts = re.findall(r"""(?:fetch|axios\.\w+|\$\.(?:get|post|ajax))\(\s*["']([^"']+)""", r.text)
            out[name] = {"url": url, "status": r.status_code, "places": {k: len(v) for k, v in places.items()},
                         "snippets": snippets[:12], "links": list(dict.fromkeys(links))[:60], "scripts": scripts[:10],
                         "text": text[:8000]}
            (OUT / f"{re.sub(r'[^a-z0-9]+', '_', name.lower())}.html").write_text(r.text[:500000], encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            out[name] = {"url": url, "error": str(exc)[:300]}
        time.sleep(1)
    (OUT / "stranice.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
