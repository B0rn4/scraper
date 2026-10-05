"""Dvadeset treći krug (faza 4): poveznice sa stranica natječaja koje nisu dale nijednu
objavu (Dobrinj, Omišalj, Krk, PGŽ, CERP, državne nekretnine) i Rijeka (wp-json)."""

import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

from curl_cffi import requests as cffi

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "debug-out") / "discovery23"
PAGES = {
    "Dobrinj": "https://dobrinj.hr/default_javnipozivi.asp?sid=5827&n=5",
    "Omišalj": "https://omisalj.hr/informacije/javni-natjecaji-i-pozivi",
    "Krk": "https://grad-krk.hr/desnibanner/natjecaji",
    "PGŽ": "https://www.pgz.hr/dokumenti/natjecaji/",
    "CERP": "https://www.cerp.hr/natjecaji/11",
    "Državne nekretnine": "http://www.hr-nekretnine.hr/",
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    s = cffi.Session(impersonate="chrome")
    out = {}
    for name, url in PAGES.items():
        try:
            r = s.get(url, timeout=40)
            links = []
            for href, inner in re.findall(r'<a[^>]+href="([^"#]+)"[^>]*>(.*?)</a>', r.text, re.S | re.I):
                text = " ".join(re.sub(r"<[^>]+>", " ", inner).split())
                if len(text) > 8:
                    links.append(f"{text[:110]} | {urljoin(str(r.url), href)}")
            out[name] = {"status": r.status_code, "final": str(r.url), "bytes": len(r.text), "links": links[:120],
                         "has_prodaj": len(re.findall(r"prodaj", r.text, re.I))}
        except Exception as exc:  # noqa: BLE001
            out[name] = {"error": str(exc)[:300]}
    r = s.get("https://www.rijeka.hr/wp-json/wp/v2/posts", params={"search": "prodaj", "per_page": 30, "orderby": "date",
                                                                   "order": "desc", "_fields": "date,title"}, timeout=40)
    out["Rijeka wp"] = [f"{x['date'][:10]} {x['title']['rendered'][:110]}" for x in r.json()] if r.status_code == 200 else r.status_code
    (OUT / "sazetak.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
