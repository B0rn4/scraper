"""Dvadeset peti krug:
1. Rijeka i ostale WordPress stranice: natječaji za prodaju u "stranicama" (pages), ne
   samo u objavama; Rijeka: objave o zemljištu.
2. Ministarstvo: "Pregled tržišta nekretnina" (ostvarene cijene kuća i stanova) – tekst PDF-a.
3. index.hr: tražene cijene stanova po gradu/općini (za odnos kuća/stan s našim medijanima)."""

import io
import json
import re
import statistics
import sys
import time
import traceback
from pathlib import Path
from urllib.parse import urljoin

from curl_cffi import requests as cffi

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.http import Http  # noqa: E402
from scraper.locations import Locator  # noqa: E402
from scraper.runner import load_config  # noqa: E402
from scraper.sources.index_oglasi import IndexOglasi  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "debug-out") / "discovery25"
WP = {"Rijeka": "https://www.rijeka.hr/", "Opatija": "https://opatija.hr/", "Crikvenica": "https://www.crikvenica.hr/",
      "Kostrena": "https://kostrena.hr/", "Malinska": "https://www.malinska.hr/", "Lovran": "https://lovran.hr/"}


def save(name, data):
    (OUT / name).write_text(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def wp_part(s, summary):
    out = {}
    for name, root in WP.items():
        item = {}
        for kind, word in (("pages", "prodaj"), ("pages", "natječaj"), ("posts", "zemljišt")):
            if kind == "posts" and name != "Rijeka":
                continue
            try:
                r = s.get(urljoin(root, f"wp-json/wp/v2/{kind}"), params={"search": word, "per_page": 30,
                                                                         "_fields": "date,link,title"}, timeout=40)
                data = r.json() if r.text.strip().startswith("[") else []
                item[f"{kind}:{word}"] = [f"{x['date'][:10]} {re.sub('<[^>]+>', '', x['title']['rendered'])[:100]} | {x['link']}"
                                          for x in data][:30]
            except Exception as exc:  # noqa: BLE001
                item[f"{kind}:{word}"] = str(exc)[:200]
            time.sleep(2)
        out[name] = item
    summary["wp"] = out


def ministry_part(s, summary):
    """Pronađi "Pregled tržišta nekretnina" na mpgi.gov.hr i izvuci tekst."""
    found, seen = [], set()
    queue = ["https://mpgi.gov.hr/default.aspx?id=8292", "https://mpgi.gov.hr/"]
    for depth in range(2):
        nxt = []
        for url in queue:
            if url in seen or len(seen) > 40:
                continue
            seen.add(url)
            try:
                html = s.get(url, timeout=40).text
            except Exception:  # noqa: BLE001
                continue
            for href, text in re.findall(r'<a[^>]+href="([^"#]+)"[^>]*>(.*?)</a>', html, re.S | re.I):
                text = " ".join(re.sub(r"<[^>]+>", " ", text).split())
                full = urljoin(url, href)
                if re.search(r"pregled\w* tržišt|tržišt\w* nekretnin|trziste|trzista", f"{text} {href}", re.I):
                    if full.lower().endswith(".pdf"):
                        found.append((text, full))
                    else:
                        nxt.append(full)
        queue = nxt
    summary["ministry_pdfs"] = found[:20]
    texts = {}
    for text, url in found[:3]:
        try:
            from pypdf import PdfReader
            data = s.get(url, timeout=120).content
            reader = PdfReader(io.BytesIO(data))
            pages = []
            for i, page in enumerate(reader.pages):
                t = page.extract_text() or ""
                if re.search(r"kuć|kuc", t, re.I) and re.search(r"Primorsko|Rijek|Opatij|Krk|Crikvenic", t):
                    pages.append(f"--- str. {i + 1} ---\n{t}")
            texts[url] = {"pages": len(reader.pages), "relevant": len(pages)}
            save(f"ministry_{len(texts)}.txt", f"{text}\n{url}\n\n" + "\n".join(pages)[:400000])
        except Exception as exc:  # noqa: BLE001
            texts[url] = str(exc)[:300]
    summary["ministry_texts"] = texts


def index_part(summary):
    cfg = load_config()
    src = IndexOglasi(Http(delay=1.5), Locator(), cfg["kriteriji"])
    rows = []
    for page in range(1, 16):
        data = src._api("flats-for-sale", page)
        for x in data.get("data") or []:
            area = (x.get("summary") or {}).get("area")
            if x.get("price") and area and 20 <= area <= 250 and x["price"] > 10000:
                rows.append({"city": x.get("cityName"), "settlement": x.get("settlementName"), "ppm": x["price"] / area})
        if not data.get("nextPage"):
            break
    by_city = {}
    for r in rows:
        by_city.setdefault(r["city"], []).append(r["ppm"])
    summary["index_flats"] = {k: {"n": len(v), "med": round(statistics.median(v))} for k, v in by_city.items()}
    summary["index_flats_total"] = len(rows)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    s = cffi.Session(impersonate="chrome")
    summary = {}
    for name, step in (("wp", lambda: wp_part(s, summary)), ("ministry", lambda: ministry_part(s, summary)),
                       ("index", lambda: index_part(summary))):
        try:
            step()
        except Exception:  # noqa: BLE001
            summary[f"{name}_error"] = traceback.format_exc()[-1500:]
        save("sazetak.json", summary)


if __name__ == "__main__":
    main()
