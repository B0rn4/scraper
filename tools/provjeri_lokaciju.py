"""Ručna provjera lokacije oglasa u ISPU-u (građevinsko područje, PPV, kulturna dobra).

Pokreće GitHub (radnja "Planovi", naredba "lokacija"), jer okruženje za razvoj ne dolazi do
portala ni do ISPU-a; rezultat ide na granu debug (planovi/lokacije/).

    python tools/provjeri_lokaciju.py IZLAZ ADRESA_OGLASA|LAT,LON|radijus:ADRESA|stranica:ADRESA|js:ADRESA
                                         |index:BROJ[,BROJ…]|index-uzorak:N [...]

index: podaci o lokaciji iz index.hr API-ja (koordinate, isPreciseLocation, sva polja s lokacijom);
index-uzorak: N najnovijih oglasa kuća i zemljišta u PGŽ-u – dijele li neprecizni oglasi istog
mjesta iste koordinate (središte mjesta) ili svaki ima svoje (približna lokacija oglasa).

Za adresu oglasa koordinate i vrsta oznake ("marker": točna, "only_area": približna) čitaju se
iz podataka stranice (nekretnine.hr, index.hr: __NEXT_DATA__ / JSON u stranici)."""

import gzip
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.http import Http  # noqa: E402
from scraper.ispu import APPROX_RADIUS_M, Ispu, _share_check, gp_text  # noqa: E402

RADII = sorted({*(r for r in APPROX_RADIUS_M.values() if r), 100, 200, 500})   # index: None (središte mjesta)
_COORDS = re.compile(r'"latitude":\s*(-?[\d.]+),\s*"longitude":\s*(-?[\d.]+)')
_MARKER = re.compile(r'"marker":\s*"(\w+)"')


def locate(http: Http, arg: str) -> dict:
    if re.fullmatch(r"-?[\d.]+,-?[\d.]+", arg):
        lat, lon = map(float, arg.split(","))
        return {"ulaz": arg, "lat": lat, "lon": lon, "oznaka": "zadano"}
    page = http.get(arg).text
    m = _COORDS.search(page)
    marker = _MARKER.search(page)
    if not m:
        return {"ulaz": arg, "greska": "na stranici nema koordinata"}
    return {"ulaz": arg, "lat": float(m.group(1)), "lon": float(m.group(2)),
            "oznaka": marker.group(1) if marker else "?"}


def find_radius(http: Http, url: str) -> dict:
    """Polumjer kruga približne oznake nije u podacima oglasa, nego u kodu karte portala: skripte
    stranice pretražuju se oko "only_area" i "radius" (isječci za ručno čitanje)."""
    page = http.get(url).text
    base = re.match(r"https?://[^/]+", url).group(0)
    scripts = list(dict.fromkeys(re.findall(r'<script[^>]+src="([^"]+\.js[^"]*)"', page)))
    found = []
    for src in scripts[:80]:
        full = src if src.startswith("http") else base + src
        try:
            js = http.get(full).text
        except Exception:  # noqa: BLE001
            continue
        found += search_js(full, js)
    return {"ulaz": url, "skripti": len(scripts), "isjecci": found[:200]}


_JS_WORDS = re.compile(r"only_area|onlyArea|[Aa]pproximate|isPreciseLocation|[Rr]adius|[Cc]ircle\(|L\.circle")


def search_js(name: str, js: str) -> list[dict]:
    return [{"skripta": name.rsplit("/", 1)[-1], "isjecak": js[max(0, m.start() - 250): m.end() + 250]}
            for m in _JS_WORDS.finditer(js)]


def save_page(http: Http, url: str, out_dir: Path) -> dict:
    """Cijela stranica oglasa (ima li kartu i koordinate?) i isječci oko koordinata."""
    from scraper.text import strip_contacts
    page = strip_contacts(http.get(url).text)      # javni repozitorij: bez kontakata
    name = re.sub(r"[^\w.-]+", "_", url.split("//", 1)[-1])[:80]
    (out_dir / f"stranica_{name}.html.gz").write_bytes(gzip.compress(page.encode("utf-8", "replace")))
    hits = [page[max(0, m.start() - 120): m.end() + 120] for m in re.finditer(
        r"(?i)latitude|longitude|\blat\b|\blng\b|\blon\b|maps\.google|google\.com/maps|leaflet|mapbox|openstreetmap|"
        r"approximate|precise|radius|circle", page)]
    return {"ulaz": url, "bajtova": len(page), "isjecci": hits[:60]}


def outline_formats(ispu: Ispu, lat: float, lon: float, out_dir: Path) -> dict:
    """Dijagnoza: koji oblik GetMap-a za slojeve građevinskog područja vraća obrise (KML je
    za te slojeve vraćao grešku GeoServera). Sirovi odgovori se spremaju."""
    from scraper.ispu import API, HEADERS, to_htrs
    cx, cy = to_htrs(lat, lon)
    box = ",".join(f"{v:.0f}" for v in (cx - 270, cy - 270, cx + 270, cy + 270))
    formats = {"kml": ("application/vnd.google-earth.kml+xml", ""),
               "kml_vektor": ("application/vnd.google-earth.kml+xml", "kmscore:100"),
               "kml_atributi": ("application/vnd.google-earth.kml+xml", "kmscore:100;kmattr:true"),
               "svg": ("image/svg+xml", ""), "png": ("image/png", ""), "json": ("application/json", ""),
               "geojson": ("application/geo+json", "")}
    out = {}
    for la in ispu.layers():
        if "Građevinska područja" not in la["_path"]:
            continue
        for name, (fmt, opts) in formats.items():
            params = {"layerHash": la["hash"], "serviceId": la["serviceId"], "SERVICE": "WMS", "VERSION": "1.1.1",
                      "REQUEST": "GetMap", "LAYERS": la["layers"], "STYLES": "", "SRS": "EPSG:3765", "BBOX": box,
                      "WIDTH": 540, "HEIGHT": 540, "FORMAT": fmt, "TRANSPARENT": "true"}
            if opts:
                params["FORMAT_OPTIONS"] = opts
            try:
                r = ispu.session.get(API + "gis/wms", params=params, headers=HEADERS, timeout=60)
                body = r.content
                key = f"{la['layers']}_{name}"
                (out_dir / f"obris_{key}.bin").write_bytes(body[:400_000])
                out[key] = {"status": r.status_code, "vrsta": r.headers.get("content-type", ""), "bajtova": len(body),
                            "pocetak": body[:200].decode("utf-8", "replace")}
            except Exception as exc:  # noqa: BLE001
                out[f"{la['layers']}_{name}"] = {"greska": f"{type(exc).__name__}: {exc}"}
            time.sleep(1)
    return out


_LOC_KEYS = re.compile(r"(?i)lat|lon|loc|precise|radius|circle|map|address|street|settlement|city|zoom")


def index_ads(http: Http, codes: list[str]) -> list[dict]:
    """Lokacija oglasa s index.hr API-ja (isti poziv kao scraper, api/aditem/single-ad)."""
    from scraper.sources.index_oglasi import BASE, JSON_HEADERS
    http.get(f"{BASE}/nekretnine/prodaja-kuca")             # kolačić
    out = []
    for code in codes:
        try:
            data = http.get(f"{BASE}/api/aditem/single-ad?code={code}&format=1", headers=JSON_HEADERS).json()
        except Exception as exc:  # noqa: BLE001
            out.append({"oglas": code, "greska": f"{type(exc).__name__}: {exc}"})
            continue
        ad = data.get("data")
        ad = ad[0] if isinstance(ad, list) and ad else ad if isinstance(ad, dict) else {}

        def walk(value, path=""):
            if isinstance(value, dict):
                for k, v in value.items():
                    yield from walk(v, f"{path}.{k}" if path else k)
            elif isinstance(value, list):
                for i, v in enumerate(value[:5]):
                    yield from walk(v, f"{path}[{i}]")
            else:
                yield path, value
        fields = {k: v for k, v in walk(ad)
                  if _LOC_KEYS.search(k.rsplit(".", 1)[-1]) and not (isinstance(v, str) and len(v) >= 120)}
        out.append({"oglas": code, "naslov": (ad.get("title") or "")[:80], "lat": ad.get("latitude"),
                    "lon": ad.get("longitude"), "isPreciseLocation": ad.get("isPreciseLocation"),
                    "mjesto": ad.get("settlementName") or ad.get("cityName"), "polja": fields,
                    **_condition(ad)})
        time.sleep(0.5)
    return out


def _condition(ad: dict) -> dict:
    """Stanje kuće prema pravilima scrapera (ruševina, za obnovu) – bez cijelog opisa: repozitorij je
    javan, a opis ima kontakt agenta. Rečenica koja je odlučila, bez e-adresa i brojeva telefona."""
    from scraper.filters import needs_renovation, ruin
    from scraper.models import HOUSE, Listing
    from scraper.text import fold
    x = Listing("index_oglasi", "", "", ad.get("title") or "", HOUSE, description=ad.get("description") or "")
    broken = ruin(x)
    from scraper.text import strip_contacts
    return {"rusevina": strip_contacts(broken),
            "za_obnovu": needs_renovation(fold(f"{x.title} {x.description}"))}


def index_sample(http: Http, n: int) -> dict:
    """N najnovijih oglasa (kuće i zemljišta, PGŽ): koordinate i preciznost; za neprecizne po
    mjestu: koliko različitih točaka."""
    from scraper.sources.index_oglasi import BASE, JSON_HEADERS, LOCATIONS
    county = json.loads(LOCATIONS.read_text(encoding="utf-8"))["id"]
    http.get(f"{BASE}/nekretnine/prodaja-kuca")
    codes = []
    for category in ("houses-for-sale", "lands-for-sale"):
        found = []
        for page in range(1, 12):
            data = http.get(f"{BASE}/api/aditem?module=real-estate&category={category}&sortOption=4&itemPerPage=24"
                            f"&page={page}&includeCountyIds={county}", headers=JSON_HEADERS).json()
            found += [str(x.get("code") or x.get("id")) for x in data.get("data") or []]
            if len(found) >= n or not data.get("nextPage"):
                break
        codes += found[:n]
        if category == "houses-for-sale":
            house_codes = set(found[:n])
    ads = index_ads(http, list(dict.fromkeys(codes))[: 2 * n])
    for a in ads:
        a["kuca"] = a["oglas"] in house_codes
    groups: dict[str, list] = {}
    for a in ads:
        if a.get("lat") is not None and not a.get("isPreciseLocation"):
            groups.setdefault(a.get("mjesto") or "?", []).append((round(a["lat"], 5), round(a["lon"], 5)))
    summary = {place: {"oglasa": len(pts), "razlicitih_tocaka": len(set(pts)), "tocke": sorted(set(pts))[:10]}
               for place, pts in groups.items()}
    houses = [a for a in ads if a.get("kuca")]
    return {"kuca": len(houses), "rusevina": [(a["oglas"], a["rusevina"]) for a in houses if a.get("rusevina")],
            "za_obnovu_bez_rusevine": sum(1 for a in houses if a.get("za_obnovu") and not a.get("rusevina")),
            "oglasa": len(ads), "preciznih": sum(1 for a in ads if a.get("isPreciseLocation")),
            "nepreciznih": sum(1 for a in ads if a.get("lat") is not None and not a.get("isPreciseLocation")),
            "bez_koordinata": sum(1 for a in ads if a.get("lat") is None),
            "neprecizni_po_mjestu": summary, "oglasi": ads}


def land_probe(ispu: Ispu, lat: float, lon: float, radius: float) -> dict:
    """Maska kopna za krug uz obalu: slojevi ISPU-a koji bi mogli pokriti samo kopno (katastar,
    granice) – daju li obrise (KML), koliko točaka i koliki je udio kopna u krugu."""
    import math
    from scraper.ispu import API, _CIRCLE_SIDES, clip_area, to_htrs
    found: list[dict] = []
    ispu._walk(ispu.session.get(API + "gis/catalog-izbornik", timeout=ispu.timeout).json(), [], found)
    cx, cy = to_htrs(lat, lon)
    circle = [(cx + radius * math.cos(2 * math.pi * i / _CIRCLE_SIDES), cy + radius * math.sin(2 * math.pi * i / _CIRCLE_SIDES))
              for i in range(_CIRCLE_SIDES)]
    box = (cx - radius - 20, cy - radius - 20, cx + radius + 20, cy + radius + 20)
    half = max(radius + 20, 300)
    query = (cx - half, cy - half, cx + half, cy + half)
    full = math.pi * radius ** 2
    out = {"ulaz": f"{lat},{lon},{radius}", "slojevi": []}
    for la in found:
        name = la["label"].get("hr", "")
        if name not in ("Katastarske općine", "Granice gradova i općina", "Granice naselja", "Morska obala"):
            continue
        t = time.monotonic()
        try:
            polys = ispu._polygons(la, query)
            land = sum(clip_area(o, box, circle) - sum(clip_area(h, box, circle) for h in hs) for o, hs in polys)
            out["slojevi"].append({"sloj": name, "serviceId": la.get("serviceId"), "obrisa": len(polys),
                                   "tocaka": sum(len(o) for o, _ in polys), "udio_kopna": round(land / full, 3),
                                   "sekundi": round(time.monotonic() - t, 1)})
        except Exception as exc:  # noqa: BLE001
            out["slojevi"].append({"sloj": name, "greska": f"{type(exc).__name__}: {exc}"[:300],
                                   "sekundi": round(time.monotonic() - t, 1)})
    return out


def main() -> int:
    out_dir, args = Path(sys.argv[1]), sys.argv[2:]
    out_dir.mkdir(parents=True, exist_ok=True)
    http, ispu, results = Http(), Ispu(), []
    for arg in args:
        if arg.startswith("obrisi:"):
            lat, lon = map(float, arg[len("obrisi:"):].split(","))
            results.append({"ulaz": arg, "oblici": outline_formats(ispu, lat, lon, out_dir)})
            continue
        if arg.startswith(("stranica:", "js:")):
            kind, _, url = arg.partition(":")
            try:
                if kind == "js":
                    # Skripta i dijelovi koje učitava (isti direktorij), npr. modul karte.
                    r = http.get(url)
                    js = r.text
                    base = url.rsplit("/", 1)[0]
                    chunks = list(dict.fromkeys(re.findall(r'["\'/]([\w.-]{6,40}\.js)["\']', js)))[:600]
                    hits = search_js(url, js)
                    for chunk in chunks:
                        try:
                            part = http.get(f"{base}/{chunk}").text
                        except Exception:  # noqa: BLE001
                            continue
                        # Samo dijelovi s kartom oglasa (inače previše isječaka tražilice).
                        if re.search(r"[Aa]pproximate|L\.circle|[Cc]ircle\(|leaflet|maplibre|mapbox", part):
                            hits += [h for h in search_js(chunk, part)
                                     if re.search(r"[Aa]pproximate|[Cc]ircle|[Rr]adius", h["isjecak"])]
                    item = {"ulaz": url, "bajtova": len(js), "pocetak": js[:200], "dijelova": len(chunks),
                            "isjecci": hits[:300]}
                else:
                    item = save_page(http, url, out_dir)
            except Exception as exc:  # noqa: BLE001
                item = {"ulaz": arg, "greska": f"{type(exc).__name__}: {exc}"}
            results.append(item)
            continue
        if arg.startswith(("index:", "index-uzorak:")):
            kind, _, value = arg.partition(":")
            try:
                item = index_ads(http, value.split(",")) if kind == "index" else index_sample(http, int(value))
            except Exception as exc:  # noqa: BLE001
                item = {"ulaz": arg, "greska": f"{type(exc).__name__}: {exc}"}
            print(json.dumps(item, ensure_ascii=False, indent=1)[:20000])
            results.append({"ulaz": arg, "rezultat": item})
            continue
        if arg.startswith("kopno:"):
            lat, lon, radius = map(float, arg[len("kopno:"):].split(","))
            try:
                item = land_probe(ispu, lat, lon, radius)
            except Exception as exc:  # noqa: BLE001
                item = {"ulaz": arg, "greska": f"{type(exc).__name__}: {exc}"}
            print(json.dumps(item, ensure_ascii=False, indent=1))
            results.append(item)
            continue
        if arg.startswith("radijus:"):
            try:
                item = find_radius(http, arg[len("radijus:"):])
            except Exception as exc:  # noqa: BLE001
                item = {"ulaz": arg, "greska": f"{type(exc).__name__}: {exc}"}
            results.append(item)
            continue
        try:
            item = locate(http, arg)
            if "lat" in item:
                center = None
                item["krug"] = {}
                own = APPROX_RADIUS_M["nekretnine_hr" if "nekretnine.hr" in arg else "default"]
                for radius in RADII:                # i drugi polumjeri, za usporedbu
                    center, shares = ispu.gp_share(item["lat"], item["lon"], radius)
                    item["krug"][radius] = {k: round(v * 100, 1) for k, v in shares.items()}
                    if radius == own:
                        item["redak"] = _share_check(center, shares, radius)
                item["sredina"] = {"gp": gp_text(center), "namjena": center.use, "blok": center.block,
                                   "ppv_gradevinsko": center.land_values,
                                   "kulturna_dobra": [h.describe() for h in center.heritage]}
        except Exception as exc:  # noqa: BLE001
            item = {"ulaz": arg, "greska": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(item, ensure_ascii=False, indent=1))
        results.append(item)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"lokacije-{time.strftime('%m%d-%H%M')}.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
