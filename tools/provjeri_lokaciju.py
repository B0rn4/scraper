"""Ručna provjera lokacije oglasa u ISPU-u (građevinsko područje, PPV, kulturna dobra).

Pokreće GitHub (radnja "Planovi", naredba "lokacija"), jer okruženje za razvoj ne dolazi do
portala ni do ISPU-a; rezultat ide na granu debug (planovi/lokacije/).

    python tools/provjeri_lokaciju.py IZLAZ ADRESA_OGLASA|LAT,LON|radijus:ADRESA|stranica:ADRESA|js:ADRESA [...]

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

RADII = sorted({*APPROX_RADIUS_M.values(), 100, 200, 500})
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
    page = http.get(url).text
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
                    chunks = list(dict.fromkeys(re.findall(r'["\'/]([\w.-]{6,40}\.js)["\']', js)))[:60]
                    hits = search_js(url, js)
                    for chunk in chunks:
                        try:
                            hits += search_js(chunk, http.get(f"{base}/{chunk}").text)
                        except Exception:  # noqa: BLE001
                            continue
                    item = {"ulaz": url, "bajtova": len(js), "pocetak": js[:200], "dijelova": len(chunks),
                            "isjecci": hits[:300]}
                else:
                    item = save_page(http, url, out_dir)
            except Exception as exc:  # noqa: BLE001
                item = {"ulaz": arg, "greska": f"{type(exc).__name__}: {exc}"}
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
