"""Trideset deveti krug: filtri cijene i površine u adresama portala (za popis stranica
koje korisnik može ručno pregledati). Za svaki portal: nazivi polja u obrascu za
pretragu, poveznice s parametrima i probne adrese s filtrima (koliko oglasa prelazi
granice prije i poslije filtra)."""

import json
import re
import sys
import time
import traceback
from pathlib import Path

from curl_cffi import requests as cffi

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.models import HOUSE, LAND  # noqa: E402
from scraper.sources import burza, nekretnine_hr, oglasnik, realestatecroatia  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "debug-out") / "discovery39"

NK = "https://www.nekretnine.hr/prodaja-samostojeca-kuce/primorsko-goranska-zupanija/"
NZ = "https://www.nekretnine.hr/prodaja-zemljista/primorsko-goranska-zupanija/"
OG = "https://oglasnik.hr/kuce-prodaja?sort=newest&f%5B4%5D%5B4559%5D=true"
OZ = "https://oglasnik.hr/zemljista-prodajem?sort=newest&f%5B4%5D%5B4559%5D=true"
RC = "https://www.realestatecroatia.com/hrv/list.asp?regija=8&vrsta=1&akcija=1&sort=objekt_id&smjer=desc"
RZ = "https://www.realestatecroatia.com/hrv/list.asp?regija=8&vrsta=3&akcija=1&sort=objekt_id&smjer=desc"
BK = "https://burza.com.hr/oglasi/nekretnine-kuce-prodaja/kvarner-i-istra"
BZ = "https://burza.com.hr/oglasi/nekretnine-zemljista-prodaja/kvarner-i-istra"
IK = "https://www.index.hr/oglasi/nekretnine/prodaja-kuca"
IZ = "https://www.index.hr/oglasi/nekretnine/prodaja-zemljista"
VE = "https://vender.hr/zupanija/primorsko-goranska/"

# (naziv, osnovna adresa, vrsta, parser, [probne adrese])
TESTS = [
    ("nekretnine kuće", NK, HOUSE, "nk", [NK + "?prezzoMassimo=400000&superficieMinima=70",
                                          NK + "?cijenaMax=400000&povrsinaMin=70"]),
    ("nekretnine zemljišta", NZ, LAND, "nk", [NZ + "?prezzoMassimo=300000&superficieMinima=300"]),
    ("oglasnik kuće", OG, HOUSE, "og", [OG + "&f%5B1%5D%5Bmax%5D=400000", OG + "&price_to=400000", OG + "&priceTo=400000"]),
    ("oglasnik zemljišta", OZ, LAND, "og", [OZ + "&f%5B1%5D%5Bmax%5D=300000"]),
    ("RC kuće", RC, HOUSE, "rc", [RC + "&cijenaDo=400000", RC + "&cijenaDo=400000&povrsinaOd=70",
                                  RC + "&cijenaDo=400000&kvadraturaOd=70"]),
    ("RC zemljišta", RZ, LAND, "rc", [RZ + "&cijenaDo=300000", RZ + "&cijenaDo=300000&povrsinaOd=300"]),
    ("burza kuće", BK, HOUSE, "bz", [BK + "?cijena_do=400000", BK + "?cijenaDo=400000", BK + "?price_to=400000"]),
    ("burza zemljišta", BZ, LAND, "bz", [BZ + "?cijena_do=300000"]),
    ("index kuće", IK, HOUSE, "", []),
    ("index zemljišta", IZ, LAND, "", []),
    ("vender", VE, HOUSE, "", []),
]


def parse(kind_name, page, kind):
    if kind_name == "nk":
        return nekretnine_hr.parse_page(page, kind)[0]
    if kind_name == "og":
        return oglasnik.parse_page(page, kind)
    if kind_name == "rc":
        return realestatecroatia.parse_list(page, kind)
    if kind_name == "bz":
        return burza.parse_list(page, kind)
    return []


def stats(items, kind):
    limit, minimum = (400_000, 70) if kind == HOUSE else (300_000, 300)
    prices = [x.price for x in items if x.price]
    return {"n": len(items), "over_price": sum(p > limit for p in prices), "max_price": max(prices, default=None),
            "under_area": sum(1 for x in items if x.area and x.area < minimum)}


def form_fields(page):
    names = sorted(set(re.findall(r"""<(?:input|select)[^>]+name=["']([^"']+)["']""", page)))
    links = sorted(set(re.findall(r"""href=["']([^"']*\?[^"']*(?:cijen|price|povr|area|kvadr|m2)[^"']*)["']""", page, re.I)))
    scripts = sorted(set(re.findall(r"""["']((?:cijena|price|povrsina|area|kvadratura)[A-Za-z_\[\]%0-9]*)["']""", page, re.I)))
    return {"fields": names[:120], "links": links[:40], "keys": scripts[:60]}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    s = cffi.Session(impersonate="chrome")
    out = {}
    for name, base, kind, parser, trials in TESTS:
        res = {}
        try:
            r = s.get(base, timeout=40)
            page = r.text
            (OUT / (re.sub(r"[^a-z0-9]+", "_", name) + ".html")).write_text(page[:800_000], encoding="utf-8")
            res["base"] = {"status": r.status_code, "final": str(r.url), **stats(parse(parser, page, kind), kind),
                           **form_fields(page)}
            for url in trials:
                time.sleep(1)
                try:
                    t = s.get(url, timeout=40)
                    res[url] = {"status": t.status_code, "final": str(t.url), **stats(parse(parser, t.text, kind), kind)}
                except Exception as exc:  # noqa: BLE001
                    res[url] = {"error": str(exc)[:200]}
        except Exception:  # noqa: BLE001
            res["error"] = traceback.format_exc()[-600:]
        out[name] = res
        (OUT / "rezultati.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        time.sleep(1)


if __name__ == "__main__":
    main()
