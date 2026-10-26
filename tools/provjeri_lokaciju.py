"""Ručna provjera lokacije oglasa u ISPU-u (građevinsko područje, PPV, kulturna dobra).

Pokreće GitHub (radnja "Planovi", naredba "lokacija"), jer okruženje za razvoj ne dolazi do
portala ni do ISPU-a; rezultat ide na granu debug (planovi/lokacije/).

    python tools/provjeri_lokaciju.py IZLAZ ADRESA_OGLASA|LAT,LON|radijus:ADRESA|stranica:ADRESA|js:ADRESA
                                         |index:BROJ[,BROJ…]|index-uzorak:N|polja:IZVOR:N [...]

index: podaci o lokaciji iz index.hr API-ja (koordinate, isPreciseLocation, sva polja s lokacijom);
index-uzorak: N najnovijih oglasa kuća i zemljišta u PGŽ-u – dijele li neprecizni oglasi istog
mjesta iste koordinate (središte mjesta) ili svaki ima svoje (približna lokacija oglasa).
polja: koja polja daju stranice oglasa (IZVOR: nekretnine, rc, index, oglasnik, vender, burza, fina – stupci
CSV-a bez opisa, napomena i osobnih podataka; IZVOR-zemljista
samo zemljišta), N oglasa po vrsti: naziv polja, u koliko oglasa ga ima i do 40 kratkih primjera vrijednosti – bez opisa,
naslova, adresa, slika, podataka o oglašivaču i slobodnog teksta (imena; repozitorij je javan). rc: i dijele li oglasi istog
mjesta koordinate s karte (središte mjesta ili točna oznaka).

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
        kinds = {k: v for k, v in walk(ad) if re.search(r"(?i)type|vrst|kind|categ|subcat|attribute", k)
                 and not (isinstance(v, str) and len(v) >= 120)}
        out.append({"oglas": code, "naslov": (ad.get("title") or "")[:80], "vrsta_polja": kinds,
                    "kljucevi": sorted(ad)[:200], "lat": ad.get("latitude"),
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


_PRIVATE = re.compile(r"(?i)phone|mail|agent|advertiser|user|contact|kontakt|owner|creator|person|company|agenc"
                      r"|descr|caption|title|url|link|href|image|photo|media|video|seo|address|adres|street|ulica|thumb")


def _flat(value, path=""):
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _flat(v, f"{path}.{k}" if path else str(k))
    elif isinstance(value, list):
        if not value:
            yield path + "[]", None
        for v in value[:40]:
            yield from _flat(v, path + "[]")
    else:
        yield path, value


def census(records: list) -> dict:
    """Polja zapisa: u koliko zapisa je polje i do 40 kratkih primjera (bez osobnih podataka;
    slobodan tekst, gdje mogu biti imena, samo kao oznaka)."""
    from collections import Counter
    from scraper.text import free_text, strip_contacts
    count, examples = Counter(), {}
    for record in records:
        seen = set()
        for path, value in _flat(record):
            if path not in seen:
                seen.add(path)
                count[path] += 1
            if value in (None, "") or _PRIVATE.search(path):
                continue
            shown = value if isinstance(value, (bool, int, float)) else (
                "(slobodan tekst)" if free_text(value) else strip_contacts(str(value))[:60])
            known = examples.setdefault(path, [])
            if shown not in known and len(known) < 40:
                known.append(shown)
    return {"zapisa": len(records),
            "polja": {path: {"n": n, "primjeri": examples.get(path, [])} for path, n in count.most_common()}}


def _distance_m(a: tuple, b: tuple) -> float:
    import math
    dy = (a[0] - b[0]) * 111_320
    dx = (a[1] - b[1]) * 111_320 * math.cos(math.radians(a[0]))
    return math.hypot(dx, dy)


def field_sample(http: Http, source: str, n: int) -> dict:
    """Polja stranica oglasa za N najnovijih oglasa po vrsti (vidi "polja:" u opisu modula).
    IZVOR-zemljista: samo zemljišta (index: i preko više stranica popisa)."""
    from scraper.models import LAND
    source, _, only = source.partition("-")
    land_only = only == "zemljista"
    records, points = [], {}
    if source == "nekretnine":
        from scraper.sources.nekretnine_hr import _NEXT_DATA, BASE, CATEGORIES, COUNTY_SLUG, parse_page
        for category, kind, _ in CATEGORIES:
            if land_only and kind != LAND:
                continue
            listings, _ = parse_page(http.get(f"{BASE}/{category}/{COUNTY_SLUG}/?criterio=data&ordine=desc&pag=1").text, kind)
            for x in listings[:n]:
                m = _NEXT_DATA.search(http.get(x.url).text)
                records.append(json.loads(m.group(1))["props"]["pageProps"].get("detailData") if m else {"greska": "nema podataka"})
    elif source == "rc":
        from scraper.sources import realestatecroatia as rc
        for vrsta, kind, _ in rc.KINDS:
            if land_only and kind != LAND:
                continue
            page = http.get(f"{rc.BASE}list.asp?regija={rc.REGION_PGZ}&vrsta={vrsta}&akcija=1&sort=objekt_id&smjer=desc&page=1").text
            for x in rc.parse_list(page, kind)[:n]:
                html_page = http.get(x.url).text
                table = re.search(r'id="podacionekretnini"(.*?)</table>', html_page, re.S)
                fields = {k.strip(): rc._clean(v)[:60] for k, v in re.findall(
                    r"<td[^>]*>\s*([^<:]{2,40}):\s*</td>\s*<td[^>]*>(.*?)</td>", table.group(1) if table else "", re.S)}
                header = rc.parse_header(html_page)
                coords = re.search(r"fromLonLat\(\[\s*(\d+)[.,](\d+)\s*,\s*(\d+)[.,](\d+)\s*\]\)", html_page)
                records.append({"vrsta": kind, "polja": fields, "zaglavlje": list(header) if header else None,
                                "koordinate": bool(coords)})
                if coords:
                    point = (float(f"{coords.group(3)}.{coords.group(4)}"), float(f"{coords.group(1)}.{coords.group(2)}"))
                    points.setdefault(header[2] if header else x.settlement, []).append(point)
    elif source == "index":
        from scraper.sources.index_oglasi import BASE, JSON_HEADERS, LOCATIONS
        county = json.loads(LOCATIONS.read_text(encoding="utf-8"))["id"]
        http.get(f"{BASE}/nekretnine/prodaja-kuca")
        for category in (("lands-for-sale",) if land_only else ("houses-for-sale", "lands-for-sale")):
            items, page = [], 1
            while len(items) < n and page <= 10:
                data = http.get(f"{BASE}/api/aditem?module=real-estate&category={category}&sortOption=4&itemPerPage=24"
                                f"&page={page}&includeCountyIds={county}", headers=JSON_HEADERS).json()
                items += data.get("data") or []
                if not data.get("nextPage"):
                    break
                page += 1
            for item in items[:n]:
                ad = http.get(f"{BASE}/api/aditem/single-ad?code={item.get('code')}&format=1", headers=JSON_HEADERS).json()
                records.append((ad.get("data") or [{}])[0])
    elif source == "oglasnik":
        from scraper.sources.oglasnik import _AD_START, _HREF, BASE, CATEGORIES, PGZ_LOCATION_ID, rsc_payload
        for category, kind in CATEGORIES:
            if land_only and kind != LAND:
                continue
            listing_page = http.get(f"{BASE}/{category}?sort=newest&page=1&f%5B4%5D%5B{PGZ_LOCATION_ID}%5D=true").text
            for href, ad_id in list(dict.fromkeys(_HREF.findall(listing_page)))[:n]:
                payload = rsc_payload(http.get(BASE + href).text)
                for m in _AD_START.finditer(payload):
                    if m.group(1) == ad_id:
                        try:
                            records.append(json.JSONDecoder().raw_decode(payload, m.start() + len('"ad":'))[0])
                        except ValueError:
                            continue
                        break
    elif source == "vender":
        from scraper.sources.vender import API, LAND_TYPES, STATE_PGZ, STATUS_SALE
        kinds = f"&property_type={','.join(str(i) for i in LAND_TYPES)}" if land_only else ""
        items = http.get(f"{API}?property_state={STATE_PGZ}&property_status={STATUS_SALE}&per_page={n}"
                         f"&_embed=wp:term{kinds}").json()
        for x in items:
            terms = [t for group in (x.get("_embedded", {}).get("wp:term") or []) for t in group]
            records.append({"property_meta": x.get("property_meta"),
                            "pojmovi": {t.get("taxonomy"): t.get("name") for t in terms if t.get("taxonomy") != "property_feature"},
                            "znacajke": [t.get("name") for t in terms if t.get("taxonomy") == "property_feature"]})
    elif source == "burza":
        from scraper.sources import burza
        for slug, kind in burza.KINDS:
            if land_only and kind != LAND:
                continue
            ads = []
            for page in (1, 2):
                ads += burza.parse_list(http.get(f"{burza.BASE}/oglasi/{slug}/{burza.REGION}"
                                                 + (f"?stranica={page}" if page > 1 else "")).text, kind)
            for x in ads[:n]:
                records.append({"vrsta": kind, "polja": burza.parse_features(http.get(x.url).text)})
    elif source == "fina":
        import csv
        import io
        from scraper.sources.fina import CSV_URL
        text = http.get(CSV_URL).content.decode("utf-8-sig", errors="replace")
        rows = [r for r in csv.DictReader(io.StringIO(text), delimiter=";")
                if (r.get("Vrsta predmeta prodaje") or "").strip() == "nekretnina"]
        hidden = re.compile(r"(?i)opis|ovr[sš]|vlasni|du[zž]ni|ste[cč]aj|\bime|oib|adres|kontakt|osob|naziv|stranka"
                            r"|razgled|napomen|uvjet")
        for r in rows[:n]:
            records.append({k: ("(skriveno)" if hidden.search(k or "") else v) for k, v in r.items()})
    else:
        return {"greska": f"nepoznat izvor {source}"}
    out = census(records)
    if points:
        out["karta_po_mjestu"] = {
            place: {"oglasa": len(pts), "razlicitih_tocaka": len(set(pts)),
                    "najveci_razmak_m": round(max(_distance_m(a, b) for a in pts for b in pts))}
            for place, pts in points.items()}
    return out


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
        if arg.startswith("polja:"):
            _, source, count = arg.split(":")
            try:
                item = field_sample(http, source, int(count))
            except Exception as exc:  # noqa: BLE001
                item = {"greska": f"{type(exc).__name__}: {exc}"}
            print(json.dumps(item, ensure_ascii=False)[:3000])
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
