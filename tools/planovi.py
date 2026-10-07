"""Prostorni planovi (PPU, UPU) za uvjete gradnje na zemljištima: najmanja građevna
čestica, koeficijent izgrađenosti (kig) i iskoristivosti (kis).

Okruženje u kojem se razvija ne dolazi do stranica planova, pa ovo radi GitHub
(tijek rada "Planovi – preuzimanje"), a rezultat sprema na granu debug (planovi/):

    python tools/planovi.py popis IZLAZ [URL…]   obiđe stranice (zadano zavod.pgz.hr): PDF-ovi s nazivima
    python tools/planovi.py preuzmi IZLAZ URL…   preuzme PDF-ove i pretvori ih u tekst
    python tools/planovi.py sn IZLAZ             popis odluka o planovima na sn.pgz.hr za naše gradove/općine

Uz zadane adrese popis prati samo poveznice koje spominju planove (FOCUS), najviše
MAX_PER_HOST stranica po stranici – stranice gradova imaju i tisuće vijesti.
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
MAX_PER_HOST = 120
FOCUS = re.compile(r"prostor|plan|urban|upu|ppu|dpu|gup|odredb|pro[cč]i[sš][cć]|slu[zž]ben|glasnik|novine|dokument"
                   r"|download|datotek", re.I)


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def popis(out: Path, start: list[str] | None = None) -> None:
    focus = bool(start)
    start = start or START
    host = {urlparse(u).netloc for u in start}
    per_host: dict[str, int] = {}
    queue, seen, docs, pages = deque(start), set(start), {}, []
    session = requests.Session()
    session.headers.update(UA)
    deadline = time.monotonic() + 35 * 60
    while queue and len(pages) < MAX_PAGES and time.monotonic() < deadline:
        url = queue.popleft()
        if focus and per_host.get(urlparse(url).netloc, 0) >= MAX_PER_HOST:
            continue
        per_host[urlparse(url).netloc] = per_host.get(urlparse(url).netloc, 0) + 1
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
                if focus and not FOCUS.search(f"{link} {_text(label)}"):
                    continue
                seen.add(link)
                queue.append(link)
        time.sleep(0.3)
    out.mkdir(parents=True, exist_ok=True)
    name = "popis.json" if not focus else f"popis_{len(list(out.glob('popis_*.json'))) + 1}.json"
    (out / name).write_text(json.dumps({"stranice": pages, "dokumenti": list(docs.values()),
                                                "neobidjeno": len(queue)}, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
    print(f"{len(pages)} stranica, {len(docs)} dokumenata, {len(queue)} neobiđeno")


SN = "https://www.sn.pgz.hr/"
# Šifre gradova i općina na sn.pgz.hr (Službene novine PGŽ-a).
SN_PLACES = {"Omišalj": "51513", "Krk": "51500", "Punat": "51521", "Baška": "10007", "Malinska-Dubašnica": "51511",
             "Vrbnik": "51516", "Dobrinj": "51514", "Opatija": "10006", "Matulji": "51211", "Lovran": "51415",
             "Rijeka": "51000", "Kostrena": "51221", "Kraljevica": "10001", "Crikvenica": "10003"}
SN_PLAN = re.compile(r"plan\w* uređenja|prostorn\w* plan|urbanističk|pročišćen", re.I)


def sn(out: Path) -> None:
    """Sve odluke s popisa svakog grada/općine (sve stranice popisa), s naslovom; zapisuje
    one koje spominju planove (sn_odluke.json)."""
    session = requests.Session()
    session.headers.update(UA)
    found = []
    for name, code in SN_PLACES.items():
        start = f"{SN}default.asp?Link=popis&sifra={code}"
        queue, seen, pages = deque([start]), {start}, 0
        while queue and pages < 80:
            url = queue.popleft()
            pages += 1
            try:
                resp = session.get(url, timeout=60)
                resp.encoding = resp.apparent_encoding or "windows-1250"
                body = resp.text
            except requests.RequestException as exc:
                found.append({"jls": name, "greska": f"{url}: {type(exc).__name__}"})
                continue
            for href, label in LINK.findall(body):
                link = urljoin(url, unescape(href.strip()))
                text = _text(label)
                if "Link=popis" in link and f"sifra={code}" in link and link not in seen:
                    seen.add(link)
                    queue.append(link)
                elif "Link=odluke" in link and SN_PLAN.search(text):
                    found.append({"jls": name, "naslov": text[:300], "url": link, "popis": url})
            time.sleep(0.3)
        print(name, pages, "stranica", sum(1 for f in found if f.get("jls") == name), "odluka")
    out.mkdir(parents=True, exist_ok=True)
    (out / "sn_odluke.json").write_text(json.dumps(found, ensure_ascii=False, indent=1), encoding="utf-8")


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
    if command == "sn":
        sn(target)
    elif command == "popis":
        popis(target, [u for arg in sys.argv[3:] for u in arg.split()])
    else:
        preuzmi(target, [u for arg in sys.argv[3:] for u in arg.split()])
