"""Faza 2a – drugi krug: vender.hr pojmovi (županija, vrsta, status) i oglasi
za PGŽ; gohome.hr pretrage s upitom kodiranim u ISO-8859-2."""

import base64
import gzip
import json
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import quote

from curl_cffi import requests as cffi

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "debug-out") / "discovery8"


def save(name, text):
    (OUT / name).write_bytes(gzip.compress(text.encode("utf-8")))


def vender(s, summary):
    base = "https://vender.hr/wp-json/wp/v2"
    for tax in ("property_state", "property_type", "property_status"):
        r = s.get(f"{base}/{tax}?per_page=100", timeout=30)
        summary[f"vender_{tax}"] = [(t["id"], t["name"], t.get("count")) for t in r.json()]
    state = next((t for t in summary["vender_property_state"] if "rimorsk" in t[1]), None)
    if state:
        r = s.get(f"{base}/properties?property_state={state[0]}&per_page=20&_embed=wp:term", timeout=30)
        save("vender_pgz.json.gz", r.text)
        items = r.json()
        summary["vender_pgz_total"] = r.headers.get("x-wp-total")
        out = []
        for x in items[:20]:
            terms = [t["name"] for group in (x.get("_embedded", {}).get("wp:term") or []) for t in group]
            meta = x.get("property_meta") or {}
            out.append({
                "id": x["id"], "date": x["date"], "title": x["title"]["rendered"][:90], "terms": terms,
                "price": meta.get("fave_property_price"), "size": meta.get("fave_property_size"),
                "land": meta.get("fave_property_land"), "addr": meta.get("fave_property_map_address"),
            })
        summary["vender_pgz"] = out
        summary["vender_meta_keys"] = sorted((items[0].get("property_meta") or {}).keys()) if items else []


def gohome(s, summary):
    queries = [
        "kuca krk prodaja",
        "kuca krk prodaja najnovije",
        "kuće Krk prodaja najnovije",
        "gradevinsko zemljiste krk prodaja najnovije",
        "kuce primorsko-goranska prodaja najnovije",
        "kuca opatija prodaja do 400000 eura najnovije",
    ]
    for i, q in enumerate(queries):
        for enc in ("iso-8859-2",):
            url = f"https://www.gohome.hr/nekretnine.aspx?q={quote(q, encoding=enc)}"
            try:
                r = s.get(url, timeout=30)
                h = r.content.decode("iso-8859-2", "replace")
                titles = re.findall(r'<span itemprop="name">([^<]+)</span>', h)
                doms = Counter(d.strip() for d in re.findall(r'class="source">([^<]+)<', h))
                dates = re.findall(r'class="indexed">([^<]+)<', h)
                urls = []
                for d in re.findall(r"RedirectTo\.aspx\?data=([A-Za-z0-9_\-=]+)", h)[:4]:
                    try:
                        urls.append(json.loads(base64.urlsafe_b64decode(d + "=" * (-len(d) % 4)))["Izvor"])
                    except Exception:  # noqa: BLE001
                        pass
                pages = sorted(set(re.findall(r"str=(\d+)", h)), key=int)
                summary[f"gohome_{i}"] = {"q": q, "status": r.status_code, "n": len(titles), "domains": dict(doms),
                                          "dates": dates[:15], "titles": titles[:8], "urls": urls, "pages": pages[-3:]}
                save(f"gohome_{i}.html.gz", h)
            except Exception as exc:  # noqa: BLE001
                summary[f"gohome_{i}"] = {"q": q, "error": str(exc)[:200]}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {}
    s = cffi.Session(impersonate="chrome")
    for fn in (vender, gohome):
        try:
            fn(s, summary)
        except Exception as exc:  # noqa: BLE001
            summary[f"{fn.__name__}_error"] = str(exc)[:300]
        (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1)[:3000])


if __name__ == "__main__":
    main()
