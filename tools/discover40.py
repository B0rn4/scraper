"""Četrdeseti krug: točan oblik filtara cijene/površine za oglasnik.hr (f[2] = cijena,
f[45] = stambena površina) i burza.com.hr (pf/pt), te filtri zemljišta na oglasniku."""

import json
import re
import sys
import time
from pathlib import Path

from curl_cffi import requests as cffi

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.models import HOUSE, LAND  # noqa: E402
from scraper.sources import burza, oglasnik  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "debug-out") / "discovery40"
OG = "https://oglasnik.hr/kuce-prodaja?sort=newest&f%5B4%5D%5B4559%5D=true"
OZ = "https://oglasnik.hr/zemljista-prodajem?sort=newest&f%5B4%5D%5B4559%5D=true"
BK = "https://burza.com.hr/oglasi/nekretnine-kuce-prodaja/kvarner-i-istra"
BZ = "https://burza.com.hr/oglasi/nekretnine-zemljista-prodaja/kvarner-i-istra"
q = lambda s: s.replace("[", "%5B").replace("]", "%5D")  # noqa: E731
TRIALS = [(OG, HOUSE, "og", OG + q(f"&{p}")) for p in
          ("f[2][max]=400000", "f[2][to]=400000", "f[2][1]=400000", "f[2][0]=0&f[2][1]=400000", "f[2][min]=0&f[2][max]=400000",
           "f[2][from]=0&f[2][to]=400000", "f[2][max]=400000&f[45][min]=70", "f[2][to]=400000&f[45][from]=70")] + \
         [(BK, HOUSE, "bz", BK + "?pt=400000"), (BK, HOUSE, "bz", BK + "?pf=0&pt=400000"), (BZ, LAND, "bz", BZ + "?pt=300000")]


def stats(items, kind):
    limit, minimum = (400_000, 70) if kind == HOUSE else (300_000, 300)
    prices = [x.price for x in items if x.price]
    return {"n": len(items), "over_price": sum(p > limit for p in prices), "max_price": max(prices, default=None),
            "under_area": sum(1 for x in items if x.area and x.area < minimum)}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    s = cffi.Session(impersonate="chrome")
    out = {}
    r = s.get(OZ, timeout=40)
    t = r.text.replace('\\"', '"')
    out["oglasnik_zemljista_filtri"] = [m.groups() for m in re.finditer(
        r'\{"slug":"([a-z_]+)","id":(\d+),"type":"([A-Z_]+)","name":"([^"]+)"', t)]
    for base, kind, parser, url in TRIALS:
        try:
            page = s.get(url, timeout=40).text
            items = oglasnik.parse_page(page, kind) if parser == "og" else burza.parse_list(page, kind)
            out[url] = stats(items, kind)
        except Exception as exc:  # noqa: BLE001
            out[url] = {"error": str(exc)[:200]}
        time.sleep(1)
    (OUT / "rezultati.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
