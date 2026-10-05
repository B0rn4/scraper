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
DOCS = "https://mpgi.gov.hr/UserDocsImages/dokumenti/stambeno/"
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
    found, seen = [("2023", f"{DOCS}Pregled-trzista-nekretnina-2023.pdf"), ("2024", f"{DOCS}Pregled-trzista-nekretnina-2024.pdf"),
                   ("2025", f"{DOCS}Pregled-trzista-nekretnina-2025.pdf"),
                   ("HNB P-41", "https://www.hnb.hr/documents/20182/2626448/p-041.pdf/a46c4569-30fc-4bb9-80e5-4f5953762d25"),
                   ("HNB I-20", "https://www.hnb.hr/documents/20182/121648/i-020.pdf/67a39d10-1fee-4447-9121-69a1f4a21f13"),
                   ("Indeksi 2025", "https://mpgi.gov.hr/UserDocsImages/Stanovanje/ProcjenaNekretnina/2025_05_23_Publikacija_indeksi.pdf")], set()
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
    for text, url in found[:9]:
        try:
            from pypdf import PdfReader
            data = s.get(url, timeout=120).content
            reader = PdfReader(io.BytesIO(data))
            pages = [f"--- str. {i + 1} ---\n{page.extract_text() or ''}" for i, page in enumerate(reader.pages)]
            texts[url] = {"pages": len(reader.pages), "bytes": len(data)}
            save(f"ministry_{len(texts)}.txt", f"{text}\n{url}\n\n" + "\n".join(pages)[:3000000])
        except Exception as exc:  # noqa: BLE001
            texts[url] = str(exc)[:300]
    summary["ministry_texts"] = texts


def index_part(summary):
    cfg = load_config()
    src = IndexOglasi(Http(delay=1.5), Locator(), cfg["kriteriji"])
    for category, key, (amin, amax) in (("flats-for-sale", "index_flats", (20, 250)),
                                        ("houses-for-sale", "index_houses", (50, 600))):
        rows = []
        for page in range(1, 31):
            data = src._api(category, page)
            for x in data.get("data") or []:
                area = (x.get("summary") or {}).get("area")
                if x.get("price") and area and amin <= area <= amax and x["price"] > 10000 and 300 <= x["price"] / area <= 20000:
                    rows.append({"city": x.get("cityName"), "settlement": x.get("settlementName"), "ppm": x["price"] / area,
                                 "area": area})
            if not data.get("nextPage"):
                break
        save(f"{key}.json", rows)
        by_city = {}
        for r in rows:
            by_city.setdefault(r["city"], []).append(r["ppm"])
        summary[key] = {k: {"n": len(v), "med": round(statistics.median(v))} for k, v in by_city.items()}
        summary[f"{key}_total"] = len(rows)


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
