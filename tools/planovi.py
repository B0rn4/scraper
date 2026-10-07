"""Prostorni planovi (PPU, UPU) za uvjete gradnje na zemljištima: najmanja građevna
čestica, koeficijent izgrađenosti (kig) i iskoristivosti (kis).

Okruženje u kojem se razvija ne dolazi do stranica planova, pa ovo radi GitHub
(tijek rada "Planovi – preuzimanje"), a rezultat sprema na granu debug (planovi/):

    python tools/planovi.py popis IZLAZ          obiđe zavod.pgz.hr: svi PDF-ovi s nazivima
    python tools/planovi.py preuzmi IZLAZ URL…   preuzme PDF-ove i pretvori ih u tekst
"""

import hashlib
import json
import re
import subprocess
import sys
import time
from collections import deque
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
START = ["https://zavod.pgz.hr/"]
DOCS = re.compile(r"\.(pdf|docx?|zip)(\?|$)", re.I)
SKIP = re.compile(r"\.(jpe?g|png|gif|svg|css|js|ico|xml|rss|mp4|dwg|tiff?)(\?|$)|^mailto:|^tel:|^javascript:", re.I)
LINK = re.compile(r"<a\b[^>]*?href=[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", re.I | re.S)
MAX_PAGES = 1500


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def popis(out: Path) -> None:
    host = {urlparse(u).netloc for u in START}
    queue, seen, docs, pages = deque(START), set(START), {}, []
    session = requests.Session()
    session.headers.update(UA)
    deadline = time.monotonic() + 35 * 60
    while queue and len(pages) < MAX_PAGES and time.monotonic() < deadline:
        url = queue.popleft()
        try:
            resp = session.get(url, timeout=30)
        except requests.RequestException as exc:
            pages.append({"url": url, "greska": f"{type(exc).__name__}"})
            continue
        kind = resp.headers.get("content-type", "")
        title = _text((re.search(r"<title[^>]*>(.*?)</title>", resp.text, re.I | re.S) or [None, ""])[1]) \
            if "html" in kind else ""
        pages.append({"url": url, "status": resp.status_code, "naslov": title})
        if "html" not in kind:
            continue
        for href, label in LINK.findall(resp.text):
            link = urljoin(resp.url, unescape(href.strip()))
            if SKIP.search(href) or not link.startswith("http"):
                continue
            if DOCS.search(link):
                docs.setdefault(link, {"url": link, "tekst": _text(label)[:200], "stranica": url, "naslov": title})
            elif urlparse(link).netloc in host and link not in seen:
                seen.add(link)
                queue.append(link)
        time.sleep(0.3)
    out.mkdir(parents=True, exist_ok=True)
    (out / "popis.json").write_text(json.dumps({"stranice": pages, "dokumenti": list(docs.values()),
                                                "neobidjeno": len(queue)}, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
    print(f"{len(pages)} stranica, {len(docs)} dokumenata, {len(queue)} neobiđeno")


def preuzmi(out: Path, urls: list[str]) -> None:
    (out / "pdf").mkdir(parents=True, exist_ok=True)
    (out / "tekst").mkdir(parents=True, exist_ok=True)
    manifest = []
    session = requests.Session()
    session.headers.update(UA)
    for url in urls:
        name = re.sub(r"[^\w.-]+", "_", Path(urlparse(url).path).name or "dokument")[-60:]
        stem = f"{hashlib.sha1(url.encode()).hexdigest()[:8]}_{Path(name).stem}"
        item = {"url": url, "datoteka": stem}
        try:
            resp = session.get(url, timeout=120)
            item.update(status=resp.status_code, vrsta=resp.headers.get("content-type", ""), velicina=len(resp.content))
            body = resp.content
            if body[:4] == b"%PDF":
                pdf = out / "pdf" / f"{stem}.pdf"
                pdf.write_bytes(body)
                txt = out / "tekst" / f"{stem}.txt"
                subprocess.run(["pdftotext", "-layout", str(pdf), str(txt)], check=False, timeout=600)
                item["znakova"] = len(txt.read_text(encoding="utf-8", errors="replace")) if txt.exists() else 0
                if len(body) > 20_000_000:
                    pdf.unlink()              # tekst je dovoljan; veliki PDF ne ide na granu
            else:
                (out / "tekst" / f"{stem}.html").write_bytes(body[:5_000_000])
        except Exception as exc:  # noqa: BLE001 – zapiši i nastavi
            item["greska"] = f"{type(exc).__name__}: {exc}"
        manifest.append(item)
        print(json.dumps(item, ensure_ascii=False))
        time.sleep(0.5)
    path = out / "preuzeto.json"
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    path.write_text(json.dumps(old + manifest, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    command, target = sys.argv[1], Path(sys.argv[2])
    if command == "popis":
        popis(target)
    else:
        preuzmi(target, [u for arg in sys.argv[3:] for u in arg.split()])
