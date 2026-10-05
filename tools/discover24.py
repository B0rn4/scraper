"""Dvadeset četvrti krug (faza 4): HTML oko "prodaj" na CERP-u i Krku; probno čitanje
izmijenjenih stranica (Omišalj, Krk RSS, Državne nekretnine)."""

import json
import re
import sys
import traceback
from pathlib import Path

from curl_cffi import requests as cffi

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.http import Http  # noqa: E402
from scraper.locations import Locator  # noqa: E402
from scraper.tenders import Reader, details, load_sites  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "debug-out") / "discovery24"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    out = {}
    s = cffi.Session(impersonate="chrome")
    for name, url in {"CERP": "https://www.cerp.hr/natjecaji/11", "Krk": "https://grad-krk.hr/desnibanner/natjecaji"}.items():
        try:
            html = s.get(url, timeout=40).text
            out[name] = [html[max(0, m.start() - 700): m.start() + 500] for m in re.finditer(r"prodaj", html, re.I)][:4]
        except Exception as exc:  # noqa: BLE001
            out[name] = str(exc)[:300]
    reader = Reader(Http(delay=1.5), Locator())
    for site in load_sites():
        if site["naziv"] not in ("Općina Omišalj", "Grad Krk (novosti)", "Državne nekretnine d.o.o."):
            continue
        try:
            items = reader.fetch(site)
            res = []
            for t in items[:6]:
                reader.load_text(t)
                res.append({"title": t.title[:150], "url": t.url, "published": t.published or t.extra.get("datum_iz_teksta"),
                            "jls": t.jls, "text_len": len(t.text), "pdf": t.extra.get("iz_pdf"), "details": details(t.text)})
            out[site["naziv"]] = res
        except Exception:  # noqa: BLE001
            out[site["naziv"]] = traceback.format_exc()[-800:]
    (OUT / "sazetak.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
