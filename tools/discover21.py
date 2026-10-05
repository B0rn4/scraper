"""Dvadeset prvi krug (faza 4): kako čitati natječaje za prodaju nekretnina na
stranicama gradova/općina, PGŽ-a, Ministarstva (državna imovina) i CERP-a.

Za svaku stranicu: RSS na početnoj, WordPress REST pretraga (wp-json) i pretraga
kroz RSS (?s=…&feed=rss2), poveznice na odjeljke "natječaji"/"prodaja"."""

import json
import re
import sys
import time
import traceback
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

from curl_cffi import requests as cffi

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "debug-out") / "discovery21"
SITES = {
    "Baška": "https://www.baska.hr/", "Dobrinj": "https://dobrinj.hr/", "Kostrena": "https://kostrena.hr/",
    "Lovran": "https://lovran.hr/", "Malinska-Dubašnica": "https://www.malinska.hr/", "Omišalj": "https://omisalj.hr/",
    "Punat": "https://punat.hr/", "Vrbnik": "https://www.opcina-vrbnik.hr/", "Crikvenica": "https://www.crikvenica.hr/",
    "Kraljevica": "https://www.kraljevica.hr/", "Krk": "https://grad-krk.hr/", "Opatija": "https://opatija.hr/",
    "Rijeka": "https://www.rijeka.hr/", "Matulji": "https://www.matulji.hr/",
    "PGŽ": "https://www.pgz.hr/", "Ministarstvo (državna imovina)": "https://mpgi.gov.hr/", "CERP": "https://www.cerp.hr/",
}
WORDS = ["natječaj", "prodaj"]
LINK_WORDS = re.compile(r"natje|natječ|prodaj|nekretnin|imovin|javni[- ]poziv|nadmetanj|licitac", re.I)


def anchors(html: str, base: str) -> list[tuple[str, str]]:
    out = []
    for href, text in re.findall(r'<a[^>]+href="([^"#]+)"[^>]*>(.*?)</a>', html, re.S | re.I):
        text = re.sub(r"<[^>]+>", " ", text)
        text = " ".join(text.split())[:120]
        url = urljoin(base, href)
        if LINK_WORDS.search(text) or LINK_WORDS.search(href):
            out.append((text, url))
    seen, uniq = set(), []
    for t, u in out:
        if u not in seen:
            seen.add(u)
            uniq.append((t, u))
    return uniq[:40]


def feed_items(xml: str) -> list[dict]:
    items = []
    for block in re.findall(r"<item>(.*?)</item>", xml, re.S)[:15]:
        title = re.search(r"<title>(.*?)</title>", block, re.S)
        link = re.search(r"<link>(.*?)</link>", block, re.S)
        date = re.search(r"<pubDate>(.*?)</pubDate>", block, re.S)
        items.append({"title": re.sub(r"<!\[CDATA\[|\]\]>", "", title.group(1)).strip()[:140] if title else "",
                      "link": link.group(1).strip() if link else "", "date": date.group(1).strip() if date else ""})
    return items


def probe_site(s, name, url) -> dict:
    res = {"url": url}
    try:
        r = s.get(url, timeout=40)
        res.update(status=r.status_code, final=str(r.url), bytes=len(r.text))
        html = r.text
        res["generator"] = (re.search(r'<meta name="generator" content="([^"]+)"', html) or [None, None])[1]
        res["wp"] = "wp-content" in html or "wp-json" in html
        res["feeds"] = re.findall(r'<link[^>]+type="application/(?:rss|atom)\+xml"[^>]+href="([^"]+)"', html, re.I)[:5]
        res["links"] = anchors(html, str(r.url))
    except Exception as exc:  # noqa: BLE001
        res["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        return res
    root = f"{urlparse(str(r.url)).scheme}://{urlparse(str(r.url)).netloc}/"
    for word in WORDS:
        try:
            r = s.get(f"{root}wp-json/wp/v2/posts?search={quote(word)}&per_page=10&_fields=id,date,link,title", timeout=40)
            data = r.json() if r.status_code == 200 and r.text.strip().startswith("[") else None
            res[f"wpjson_{word}"] = {"status": r.status_code, "n": len(data) if data is not None else None,
                                     "titles": [f"{x['date'][:10]} {re.sub('<[^>]+>', '', x['title']['rendered'])[:110]}" for x in (data or [])][:10]}
        except Exception as exc:  # noqa: BLE001
            res[f"wpjson_{word}"] = {"error": str(exc)[:150]}
        try:
            r = s.get(f"{root}?s={quote(word)}&feed=rss2", timeout=40)
            res[f"searchfeed_{word}"] = {"status": r.status_code, "ctype": r.headers.get("content-type", "")[:40],
                                         "items": feed_items(r.text)[:8] if "<rss" in r.text[:500] else None}
        except Exception as exc:  # noqa: BLE001
            res[f"searchfeed_{word}"] = {"error": str(exc)[:150]}
        time.sleep(1)
    for feed in res.get("feeds") or [f"{root}feed/"]:
        try:
            r = s.get(urljoin(root, feed), timeout=40)
            res.setdefault("feed_items", {})[feed] = feed_items(r.text)[:8] if "<rss" in r.text[:500] else f"status {r.status_code}"
        except Exception as exc:  # noqa: BLE001
            res.setdefault("feed_items", {})[feed] = str(exc)[:150]
    return res


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    s = cffi.Session(impersonate="chrome")
    summary = {}
    for name, url in SITES.items():
        try:
            summary[name] = probe_site(s, name, url)
        except Exception:  # noqa: BLE001
            summary[name] = {"error": traceback.format_exc()[-800:]}
        (OUT / "sazetak.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
