"""ISPU (Ministarstvo prostornoga uređenja): podaci za točku ili katastarsku česticu.

Isti pozivi koje koristi preglednik na ispu.mgipu.hr, bez prijave:
- POST api/v1/gis/identify – slojevi na točki (građevinsko područje, PPV zemljišta);
- GET api/v1/gis/search-kat-opcina?input=… – matični broj katastarske općine;
Čestica (točka unutar nje i površina) dolazi iz javnog katastarskog servisa DGU-a
(INSPIRE WFS, nationalCadastralReference = "matični broj k.o.-broj čestice").
Koordinate su u HTRS96/TM (EPSG:3765); pretvorba je ovdje, bez dodatnih biblioteka
(radi i na Redmiju). Slojevi se pronalaze po nazivu u katalogu, jer se brojevi
slojeva mijenjaju sa svakim novim PPV-om."""

import json
import math
import re
import time
from dataclasses import dataclass, field

from .text import fmt_m2, fold

API = "https://ispu.mgipu.hr/api/v1/"
# Približna oznaka na karti oglasa (krug na portalu): točan udio kruga u građevinskom području, iz
# obrisa slojeva (GeoServer Ministarstva kroz ISPU-ov WMS posrednik, KML). Polumjer kruga portal
# ne navodi u podacima oglasa – APPROX_RADIUS_M po izvoru (izmjereno s karte portala).
APPROX_RADIUS_M = {"default": 300,
                   "nekretnine_hr": 250,   # kod karte portala: krug "only_area" polumjera 250 m (8. 10. 2026.)
                   "njuskalo": 500,        # stranica oglasa: mapBox.circle.radius (čita se i iz svakog oglasa)
                   # index.hr: "neprecizna" lokacija su koordinate mjesta iz izbornika (kod portala,
                   # isPreciseLocation=false), ne krug oko čestice – postotak bi zavaravao.
                   "index_oglasi": None}
_CIRCLE_SIDES = 256
_PLACEMARK = re.compile(r"<Placemark[^>]*>(.*?)</Placemark>", re.S)
_POLYGON = re.compile(r"<Polygon>(.*?)</Polygon>", re.S)
_OUTER = re.compile(r"<outerBoundaryIs>.*?<coordinates>(.*?)</coordinates>", re.S)
_INNER = re.compile(r"<innerBoundaryIs>.*?<coordinates>(.*?)</coordinates>", re.S)
CP_WFS = "https://api.uredjenazemlja.hr/services/inspire/cp/wfs"   # DGU, katastarske čestice (INSPIRE)
PGZ_OFFICES = {"rijeka", "krk", "crikvenica", "opatija", "delnice", "rab", "mali losinj", "cres", "cabar",
               "vrbovsko", "novi vinodolski"}
HEADERS = {"Accept": "application/json", "Content-Type": "application/json",
           "Origin": "https://ispu.mgipu.hr", "Referer": "https://ispu.mgipu.hr/"}

# GRS80, poprečna Mercatorova projekcija: srednji meridijan 16,5°, mjerilo 0,9999.
_A, _F = 6378137.0, 1 / 298.257222101
_E2 = _F * (2 - _F)
_EP2 = _E2 / (1 - _E2)
_K0, _LON0, _FE = 0.9999, math.radians(16.5), 500000.0


def to_htrs(lat: float, lon: float) -> tuple[float, float]:
    """WGS84/ETRS89 (stupnjevi) → HTRS96/TM (metri, istok/sjever)."""
    phi, lam = math.radians(lat), math.radians(lon)
    e4, e6 = _E2 ** 2, _E2 ** 3
    n = _A / math.sqrt(1 - _E2 * math.sin(phi) ** 2)
    t = math.tan(phi) ** 2
    c = _EP2 * math.cos(phi) ** 2
    a = (lam - _LON0) * math.cos(phi)
    m = _A * ((1 - _E2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi
              - (3 * _E2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * math.sin(2 * phi)
              + (15 * e4 / 256 + 45 * e6 / 1024) * math.sin(4 * phi)
              - (35 * e6 / 3072) * math.sin(6 * phi))
    x = _FE + _K0 * n * (a + (1 - t + c) * a ** 3 / 6 + (5 - 18 * t + t * t + 72 * c - 58 * _EP2) * a ** 5 / 120)
    y = _K0 * (m + n * math.tan(phi) * (a * a / 2 + (5 - t + 9 * c + 4 * c * c) * a ** 4 / 24
                                        + (61 - 58 * t + t * t + 600 * c - 330 * _EP2) * a ** 6 / 720))
    return x, y


# --- katastarske čestice u tekstu oglasa ------------------------------------

# Broj čestice; "7/9 dijela" je suvlasnički udio, ne čestica.
_KC_NUM = r"\d{1,5}(?:/\d{1,4})?(?![\d/])(?!\s*(?:dijel|dio\b|udjel|udio))"
_KC = re.compile(
    # z.k.č. / zk.č. / z.č.: zemljišnoknjižna čestica (na Krku broj često nije isti kao katastarski)
    r"(?:(?P<zk>\bz\.?\s*k\.?\s*č\.?|\bzk\.?\s*č\.?|\bz\.\s*č\.?|\bzkčbr\.?)\s*(?:br\.?|broj)?"
    r"|\bk\.?\s*č\.?\s*(?:br\.?|broj)?|\bčkbr\.?|\bkčbr\.?|\bčest(?:ica|ice|ici|\.)\s*(?:br\.?|broj)?)"
    r"\s*:?\s*(?P<nums>" + _KC_NUM + r"(?:\s*(?:,|i|te)\s*" + _KC_NUM + r")*)", re.I)
_KO_WORD = r"(?:Sv\.\s*)?[A-ZČĆŽŠĐ][\wčćžšđČĆŽŠĐ-]*"
_KO = re.compile(r"\b(?i:k\.?\s*o\.?)\s*:?\s+(" + _KO_WORD + r"(?:(?:\s*[-–]\s*|\s+)" + _KO_WORD + r")*)")
# Riječi iza naziva k.o. koje nisu dio naziva ("k.o. Punat Početna natječajna cijena…").
_KO_STOP = set("""pocetna pocetne pocetnu napomena napomene povrsina povrsine povrsinom cijena jamcevina predmet
ukupno ukupne ukupna upisana upisane upisan upisano opis namjena vlasnistvo zemljiste zemljista nekretnina
nekretnine kupoprodajna prema sukladno grad grada opcina opcine u na i te zk dio oznaka oznake ponuda rok prodaja
prodaje natjecaj javni oglas kuca obiteljska""".split())


def clean_ko(raw: str) -> str:
    """Naziv k.o. iz teksta: "Malinska – Dubašnica" → "Malinska-Dubašnica"; bez riječi koje
    slijede iza naziva ("Punat Početna", "Volosko NAPOMENA"); najviše tri riječi."""
    parts = re.split(r"(\s*[-–]\s*|\s+)", raw.strip())
    words, seps = parts[0::2], parts[1::2]
    if not words or not words[0]:
        return ""
    out = words[0]
    for n, (sep, w) in enumerate(zip(seps, words[1:]), start=2):
        if n > 3 or fold(w).strip(".") in _KO_STOP or (w.isupper() and len(w) > 2 and not words[0].isupper()):
            break
        out += ("-" if re.search(r"[-–]", sep) else " ") + w
    return re.sub(r"(\s+\w)+$", "", out)


@dataclass
class Mention:
    start: int
    end: int
    ko: str
    kcs: list[str]
    land_registry: bool = False     # z.k.č. (zemljišnoknjižna oznaka), ne katastarska


def parcel_mentions(text: str) -> list[Mention]:
    """Spomeni čestica u tekstu. Čestica se veže uz najbližu sljedeću (ili prethodnu)
    oznaku k.o. Zemljišnoknjižna oznaka uz koju odmah slijedi katastarska ("zk.č. 1523
    (k.č. 2775/3)") se preskače."""
    text = text or ""
    kos = [(m.start(), clean_ko(m.group(1))) for m in _KO.finditer(text)]
    found = list(_KC.finditer(text))
    out = []
    for i, m in enumerate(found):
        zk = bool(m.group("zk"))
        if zk and i + 1 < len(found) and not found[i + 1].group("zk") and found[i + 1].start() - m.end() < 40:
            continue
        after = [ko for pos, ko in kos if pos >= m.end() and pos - m.end() < 250]
        before = [ko for pos, ko in kos if pos < m.start() and m.start() - pos < 120]
        near = [ko for pos, ko in kos if pos >= m.end() and pos - m.end() < 120]
        ko = near[0] if near else before[-1] if before else after[0] if after else ""
        kcs = [kc for kc in re.split(r"\s*(?:,|\bi\b|\bte\b)\s*", m.group("nums")) if kc]
        if ko and kcs:
            out.append(Mention(m.start(), m.end(), ko, kcs, zk))
    return out


def parcels_in_text(text: str) -> list[tuple[str, str]]:
    """[(katastarska općina, broj čestice)] iz teksta, npr. "k.č. 1234/5, k.o. Njivice".
    Katastarske oznake prije zemljišnoknjižnih."""
    out = []
    for m in sorted(parcel_mentions(text), key=lambda m: m.land_registry):
        for kc in m.kcs:
            if (fold(m.ko), kc) not in {(fold(k), c) for k, c in out}:
                out.append((m.ko, kc))
    return out[:5]


def wkt_centroid(wkt: str) -> tuple[float, float] | None:
    """Težište poligona iz WKT-a (prvi prsten; dovoljno za česticu)."""
    nums = re.findall(r"(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)", wkt or "")
    pts = [(float(x), float(y)) for x, y in nums]
    if len(pts) < 3:
        return pts[0] if pts else None
    area = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        cross = x0 * y1 - x1 * y0
        area += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if abs(area) < 1e-9:
        return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
    return cx / (3 * area), cy / (3 * area)


# --- rezultat i klijent -----------------------------------------------------

RESIDENTIAL = re.compile(r"^(GP|S\d?$|S-|M\d?$|M-)")
# Opis koji spominje staru/povijesnu jezgru (za približnu lokaciju unutar zaštićene cjeline).
OLD_CORE = re.compile(r"\bstar\w* (gradsk\w* |povijesn\w* )?jezgr|\bpovijesn\w* jezgr|\bu starom gradu\b|\bstari grad\b"
                      r"|\bstarogradsk|\bkulturno povijesn")


@dataclass
class Heritage:
    """Zaštićeno nepokretno kulturno dobro (Registar kulturnih dobara, sloj u ISPU-u)."""
    name: str
    number: str = ""               # registarski broj: Z-… (zaštićeno) ili P-… (preventivno)
    kind: str = ""                 # vrsta, npr. "Kulturnopovijesne cjeline"
    classification: str = ""       # npr. "urbana cjelina", "stambena građevina"

    @property
    def area(self) -> bool:
        """Cjelina, zona ili krajolik (a ne pojedinačna građevina)."""
        return bool(re.search(r"cjelin|zon|krajolik|nalazi", f"{self.kind} {self.classification}", re.I))

    def describe(self) -> str:
        text = f"{self.kind} {self.classification}".lower()
        what = ("u arheološkoj zoni" if "arheolo" in text else "u kulturnom krajoliku" if "krajolik" in text
                else "u kulturno-povijesnoj cjelini" if "cjelin" in text else "zaštićeno kulturno dobro")
        if self.number.startswith("P"):
            what = what.replace("zaštićeno", "preventivno zaštićeno") if what.startswith("zaštićeno") \
                else f"{what} (preventivno zaštićenoj)"
        name = self.name if len(self.name) <= 80 else self.name[:77] + "…"
        return f"{what} „{name}”" + (f" ({self.number})" if self.number else "")


@dataclass
class PointInfo:
    gp: str | None = None          # "naselja", "izvan naselja" ili None (izvan građevinskog područja)
    gp_plan: str = ""              # prostorni plan iz kojeg je granica
    block: str = ""                # cjenovni blok PPV-a
    use: str = ""                  # pretežita namjena bloka, npr. "(GP) IZGRAĐENI DIO GRAĐEVINSKOG PODRUČJA NASELJA"
    land_values: list[float] = field(default_factory=list)   # PPV građevinskog zemljišta stambene/mješovite namjene
    ppv_label: str = ""
    heritage: list[Heritage] = field(default_factory=list)  # zaštićena kulturna dobra na točki
    heritage_checked: bool = True                           # False: ISPU nije odgovorio za slojeve baštine


class Ispu:
    def __init__(self, session=None, timeout: int = 30):
        if session is None:
            from curl_cffi import requests as cffi
            session = cffi.Session(impersonate="chrome")
        self.session = session
        self.timeout = timeout
        self._layers: list[dict] | None = None
        self.parcels_off = False         # DGU nije odgovorio: do kraja pokretanja bez traženja čestica
        self.last_miss = ""              # zašto čestica nije nađena: "ko", "kc" ili "off" (servis ne radi)
        self.retry_pause = 1.0           # razmak prije ponovnog upita (s)

    def layers(self) -> list[dict]:
        """Slojevi građevinskog područja, najnoviji PPV zemljišta i zaštićena kulturna dobra
        (Z- i P-lista Ministarstva kulture i medija) iz kataloga."""
        if self._layers is None:
            found: list[dict] = []
            self._walk(self.session.get(API + "gis/catalog-izbornik", timeout=self.timeout).json(), [], found)
            gp = [la for la in found if "Građevinska područja" in la["_path"] and la["hashIdentify"]]
            ppv = [la for la in found if re.match(r"PPV 1\.1\.\d{4}\. – zemljišta", la["label"].get("hr", ""))]
            ppv.sort(key=lambda la: la["label"]["hr"], reverse=True)
            heritage = [la for la in found if "Nepokretna kulturna dobra po statusu zaštite" in la["_path"] and la["hashIdentify"]]
            self._layers = gp + ppv[:1] + heritage
        return self._layers

    def ppv_year(self) -> int | None:
        """Najnovija godina PPV-a za zemljišta u katalogu ISPU-a (za podsjetnik o osvježavanju)."""
        found: list[dict] = []
        self._walk(self.session.get(API + "gis/catalog-izbornik", timeout=self.timeout).json(), [], found)
        years = [int(m.group(1)) for la in found
                 if (m := re.match(r"PPV 1\.1\.(\d{4})\. – zemljišta", la["label"].get("hr", "")))]
        return max(years) if years else None

    def _walk(self, node, path, out):
        if isinstance(node, dict):
            label = node.get("label") if isinstance(node.get("label"), dict) else None
            p = path + [label.get("hr", "")] if label else path
            if label and node.get("type") == "sloj":
                ext = node.get("extensionData") or {}
                out.append({"id": node.get("id"), "hashIdentify": (node.get("info") or {}).get("hashIdentify"),
                            "serviceId": ext.get("serviceId"), "layers": (ext.get("params") or {}).get("layers"),
                            "hash": ext.get("layerHash"), "label": label, "_path": " > ".join(p)})
            for v in node.values():
                self._walk(v, p, out)
        elif isinstance(node, list):
            for v in node:
                self._walk(v, path, out)

    def identify(self, x: float, y: float) -> PointInfo:
        """Slojevi na točki. ISPU povremeno vrati 400 ("pokušajte ponovo") kad upiti idu brzo
        zaredom (mjerenje 6. 10.: 3 od 36 bez razmaka, 0 od 36 s razmakom od 1 s): ponovi
        nakon 1 s, a zatim bez slojeva kulturnih dobara (građevinsko područje je važnije)."""
        layers = self.layers()
        base = [la for la in layers if "kulturna dobra" not in la["_path"]]
        attempts = [layers, layers] + ([base] if len(base) < len(layers) else [])
        for i, use in enumerate(attempts):
            if i:
                time.sleep(self.retry_pause)
            body = {"x": x, "y": y, "scale": 2000, "layers": [{k: v for k, v in la.items() if not k.startswith("_")} for la in use]}
            r = self.session.post(API + "gis/identify", json=body, headers=HEADERS, timeout=self.timeout)
            if r.status_code < 400 or i == len(attempts) - 1:
                r.raise_for_status()
                info = parse_identify(r.json())
                info.heritage_checked = len(use) == len(layers)
                return info
        raise RuntimeError("ISPU identify")          # ne događa se: zadnji pokušaj vraća ili baca grešku

    def point(self, lat: float, lon: float) -> PointInfo:
        return self.identify(*to_htrs(lat, lon))

    def gp_share(self, lat: float, lon: float, radius: float) -> tuple[PointInfo, dict[str, float]]:
        """Približna oznaka: svi slojevi u središtu (blok PPV-a kaže naselje) i točan udio kruga
        polumjera radius u građevinskom području naselja i izvan naselja (0–1)."""
        cx, cy = to_htrs(lat, lon)
        center = self.identify(cx, cy)
        circle = [(cx + radius * math.cos(2 * math.pi * i / _CIRCLE_SIDES),
                   cy + radius * math.sin(2 * math.pi * i / _CIRCLE_SIDES)) for i in range(_CIRCLE_SIDES)]
        box = (cx - radius - 20, cy - radius - 20, cx + radius + 20, cy + radius + 20)
        half = max(radius + 20, 300)        # upit: obrisi koji sijeku kvadrat dolaze cijeli
        query = (cx - half, cy - half, cx + half, cy + half)
        full = math.pi * radius ** 2 * math.cos(math.pi / _CIRCLE_SIDES) * math.sin(math.pi / _CIRCLE_SIDES) \
            / (math.pi / _CIRCLE_SIDES)                    # površina 256-kuta (≈ krug)
        shares: dict[str, float] = {}
        for la in self.layers():
            if "Građevinska područja" not in la["_path"]:
                continue
            kind = "izvan naselja" if "izvan naselja" in la["label"].get("hr", "") else "naselja"
            area = sum(clip_area(outer, box, circle) - sum(clip_area(h, box, circle) for h in holes)
                       for outer, holes in self._polygons(la, query))
            shares[kind] = min(1.0, shares.get(kind, 0.0) + max(0.0, area) / full)
        return center, shares

    def _polygons(self, layer: dict, box: tuple[float, float, float, float]) -> list[tuple[list, list[list]]]:
        """Obrisi sloja koji sijeku pravokutnik (HTRS96/TM): [(vanjski prsten, [rupe])]."""
        params = {"layerHash": layer["hash"], "serviceId": layer["serviceId"], "SERVICE": "WMS", "VERSION": "1.1.1",
                  "REQUEST": "GetMap", "LAYERS": layer["layers"], "STYLES": "", "SRS": "EPSG:3765",
                  "BBOX": ",".join(f"{v:.0f}" for v in box), "WIDTH": 540, "HEIGHT": 540, "TRANSPARENT": "true",
                  "FORMAT": "application/vnd.google-earth.kml+xml", "FORMAT_OPTIONS": "kmscore:100"}
        # GeoServer je jednom vratio NullPointerException za mali kvadrat: drugi pokušaj bez opcija.
        for attempt in range(2):
            if attempt:
                time.sleep(self.retry_pause)
                params.pop("FORMAT_OPTIONS", None)
            r = self.session.get(API + "gis/wms", params=params, headers=HEADERS, timeout=self.timeout)
            if r.status_code == 200 and "<kml" in r.text[:2000]:
                break
        else:
            raise RuntimeError(f"ISPU obrisi građevinskog područja: HTTP {r.status_code} "
                               f"({r.headers.get('content-type', '')}) {r.text[:300]!r}")

        def ring(coords: str) -> list[tuple[float, float]]:
            pts = [c.split(",") for c in coords.split()]
            return [to_htrs(float(p[1]), float(p[0])) for p in pts if len(p) >= 2]

        out = []
        for placemark in _PLACEMARK.findall(r.text):
            for poly in _POLYGON.findall(placemark):
                outer = _OUTER.search(poly)
                if outer:
                    out.append((ring(outer.group(1)), [ring(h) for h in _INNER.findall(poly)]))
        return out

    def parcel(self, ko_name: str, kc: str, names: dict[str, str] | None = None) -> dict | None:
        """Točka unutar čestice (HTRS96) i površina: {"x", "y", "povrsina"} ili None.
        K.o. → matični broj iz ISPU-a; čestica iz javnog katastarskog servisa DGU-a
        (INSPIRE). names: normalizirani naziv → naziv s dijakriticima (pretraga ISPU-a
        traži dijakritike: "OMIŠALJ", ne "OMISALJ")."""
        self.last_miss = "off"
        if self.parcels_off:
            return None
        mbr = self.cadastral_municipality(ko_name)
        if mbr is None and names and fold(ko_name) in names:
            mbr = self.cadastral_municipality(names[fold(ko_name)])
        if mbr is None:
            self.last_miss = "ko"
            return None
        self.last_miss = "kc"
        for label in (kc, "*" + kc):     # "*" su zgradne čestice
            try:
                r = self.session.get(CP_WFS, params={
                    "service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": "cp:CadastralParcel",
                    "count": 1, "outputFormat": "application/json",
                    # Ovaj oblik filtra je najbrži (~15 s); točna jednakost oznake traje ~35 s.
                    "CQL_FILTER": f"label='{label}' AND nationalCadastralReference LIKE '{mbr}-%'"},
                    timeout=max(self.timeout, 45))
                r.raise_for_status()
            except Exception:
                self.parcels_off = True
                raise
            features = r.json().get("features") or []
            if features:
                props = features[0].get("properties") or {}
                point = (props.get("referencePoint") or {}).get("coordinates")
                if not point:
                    point = wkt_centroid(json.dumps((features[0].get("geometry") or {}).get("coordinates")))
                if point:
                    return {"x": point[0], "y": point[1], "povrsina": (props.get("areaValue") or {}).get("value")}
        return None

    def cadastral_municipality(self, ko_name: str) -> str | None:
        """Matični broj katastarske općine. Pretraga traži velika slova s dijakriticima;
        labela je "URED, K.O." (npr. "KRK, OMIŠALJ"). Iz teksta naziv zna povući i
        sljedeću riječ ("Punat Početna cijena…"), pa se kraće varijante probaju redom."""
        name = re.sub(r"\s*-\s*", "-", ko_name.strip())
        if re.match(r"(?i)sv\.\s*", name):          # "Sv. Jelena" → "Sveta Jelena" / "Sveti …"
            rest = re.sub(r"(?i)^sv\.\s*", "", name)
            return next((m for full in (f"Sveta {rest}", f"Sveti {rest}") if (m := self.cadastral_municipality(full))), None)
        words = name.split()
        candidates = [" ".join(words[:n]) for n in range(len(words), 0, -1)]
        if "-" in words[0]:
            candidates.append(words[0].split("-")[0])      # "Njivice-Prodaja" iz "k.o. Njivice - Prodaja"
        for candidate in candidates:
            for query in dict.fromkeys([candidate, candidate.replace("-", " ")]):
                r = self.session.get(API + "gis/search-kat-opcina", params={"input": query.upper()}, timeout=self.timeout)
                r.raise_for_status()
                want = fold(candidate)
                found = [(k, fold(str(k.get("labela", "")).split(",")[-1])) for k in r.json() or []]
                matches = [k for k, label in found if label == want]
                if matches:
                    # Isti naziv k.o. postoji u više županija (npr. Vrh): prednost uredima u PGŽ-u.
                    matches.sort(key=lambda k: fold(str(k.get("labela", "")).split(",")[0]) not in PGZ_OFFICES)
                    return matches[0]["maticniBroj"]
        return None


def parse_identify(data) -> PointInfo:
    info = PointInfo()
    for layer in data if isinstance(data, list) else (data or {}).get("data") or []:
        label = (layer.get("label") or {}).get("hr", "")
        for item in layer.get("items") or []:
            fields = [((x.get("label") or {}).get("hr", ""), x.get("value") or "") for x in item.get("items") or []]
            f = dict(fields)
            if "Registarski broj" in f:            # kulturno dobro (isti objekt može biti u više slojeva)
                h = Heritage(f.get("Naziv", "").strip(), f["Registarski broj"].strip(), f.get("Vrsta", ""),
                             f.get("Klasifikacija", ""))
                if h.name and all((h.number or h.name) != (o.number or o.name) for o in info.heritage):
                    info.heritage.append(h)
            elif label.startswith("Građevinsko područje"):
                kind = "izvan naselja" if "izvan naselja" in label else "naselja"
                if info.gp != "naselja":
                    info.gp = kind
                info.gp_plan = info.gp_plan or dict(fields).get("Naziv plana iz kojeg su preuzeti podaci", "")
            elif label.startswith("PPV"):
                info.ppv_label = label
                vrsta = namjena = ""
                for name, value in fields:
                    if name == "Naziv cjenovnog bloka":
                        info.block = value
                    elif name == "Pretežita namjena":
                        info.use = value
                    elif name == "Vrsta zemljišta":
                        vrsta = value
                    elif name == "Namjena zemljišta":
                        namjena = value
                    elif name.startswith("Približne vrijednosti zemljišta") and value:
                        if vrsta.startswith("Građevinsko") and RESIDENTIAL.search(namjena):
                            info.land_values.append(float(value))
    return info


# --- provjera zemljišta iz oglasa -------------------------------------------

@dataclass
class LandCheck:
    line: str                      # redak za obavijest (🗺 …)
    warning: str = ""              # ⚠ kad zemljište nije u građevinskom području naselja
    info: PointInfo | None = None  # podaci ISPU-a (za PPV na lokaciji)
    heritage: str = ""             # ⚠ zaštićeno kulturno dobro / cjelina na lokaciji


def heritage_warning(items: list[Heritage], caveat: str = "", land: bool = False) -> str:
    """⚠ za zaštićena kulturna dobra na točki: najviše dva, cjeline prve. Za zemljište: nova
    gradnja nije zabranjena, ali traži posebne uvjete i potvrdu projekta konzervatora
    (ovisno o zoni zaštite: oblik, visina, materijali; u arheološkoj zoni i istraživanja)."""
    if not items:
        return ""
    items = sorted(items, key=lambda h: not h.area)[:2]
    if not land:
        what = "radovi uz uvjete konzervatora"
    elif any("arheolo" in f"{h.kind} {h.classification}".lower() for h in items):
        what = "gradnja uz uvjete konzervatora (moguća arheološka istraživanja)"
    else:
        what = "nova gradnja uz uvjete konzervatora (oblik, visina, materijali)"
    return "; ".join(h.describe() for h in items) + f" – {what}{caveat}"


def check_land(ispu: "Ispu", text: str, lat: float | None, lon: float | None, approximate: bool,
               names: dict[str, str] | None = None, house: bool = False,
               radius: float | None = APPROX_RADIUS_M["default"]) -> LandCheck:
    """Je li zemljište (ili kuća) u građevinskom području: prvo po katastarskoj čestici iz
    teksta (točno), inače po oznaci na karti oglasa (ako portal kaže da nije približna)."""
    parcels = parcels_in_text(text)
    info, where = None, ""
    for ko, kc in parcels[:3]:
        found = ispu.parcel(ko, kc, names)
        if found:
            info = ispu.identify(found["x"], found["y"])
            area = f", {fmt_m2(found['povrsina'])}" if found.get("povrsina") else ""
            where = f"k.č. {kc} k.o. {ko}{area}"
            break
    if info is None and lat and lon and not approximate:
        info, where = ispu.point(lat, lon), "oznaci na karti oglasa"
    if info is None:
        why = "čestica iz oglasa nije pronađena u katastru" if parcels else (
            "oglas ima samo mjesto (ne lokaciju čestice)" if lat and lon and approximate and radius is None
            else "oglas nema točnu lokaciju ni broj čestice")
        line, warning = f"🗺 Građevinsko područje: nije provjereno – {why}", ""
        if lat and lon and approximate and radius and not house and hasattr(ispu, "gp_share"):
            line, warning = _share_check(*ispu.gp_share(lat, lon, radius), radius)
        heritage = ""
        if lat and lon and OLD_CORE.search(fold(text)):
            # Približna oznaka + opis spominje staru jezgru: provjera samo za cjeline (ne pojedinačne građevine).
            try:
                areas = [h for h in ispu.point(lat, lon).heritage if h.area]
            except Exception:  # noqa: BLE001 – samo dodatna provjera
                areas = []
            if areas:
                heritage = "vjerojatno " + heritage_warning(
                    areas, " (opis spominje staru jezgru, oznaka na karti je približna)", land=not house)
        return LandCheck(line, warning, heritage=heritage)
    caveat = " (oznaka može biti približna)" if where.startswith("oznaci") else ""
    result = _gp_check(info, where, caveat, house, use=info.use.split(") ", 1)[-1].capitalize() if info.use else "")
    result.heritage = heritage_warning(info.heritage, caveat, land=not house)
    if not info.heritage_checked:
        result.line += " (kulturna dobra nisu provjerena – ISPU nije odgovorio)"
    return result


def clip_area(ring: list[tuple[float, float]], box: tuple[float, float, float, float],
              circle: list[tuple[float, float]]) -> float:
    """Površina dijela prstena (poligona) unutar kruga (konveksni mnogokut, suprotno od kazaljke):
    prvo odsijecanje pravokutnikom oko kruga (manje točaka), zatim krugom (Sutherland–Hodgman)."""
    x0, y0, x1, y1 = box
    for clip in ([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], circle):
        for i in range(len(clip)):
            if not ring:
                return 0.0
            (ax, ay), (bx, by) = clip[i - 1], clip[i]
            inside = [(bx - ax) * (py - ay) - (by - ay) * (px - ax) >= 0 for px, py in ring]
            out = []
            for j, (px, py) in enumerate(ring):
                sx, sy = ring[j - 1]
                if inside[j] != inside[j - 1]:       # brid prelazi granicu: sjecište
                    dx, dy = px - sx, py - sy
                    den = (bx - ax) * dy - (by - ay) * dx
                    t = ((bx - ax) * (ay - sy) - (by - ay) * (ax - sx)) / den if den else 0.0
                    out.append((sx + t * dx, sy + t * dy))
                if inside[j]:
                    out.append((px, py))
            ring = out
    return abs(sum(ax * by - bx * ay for (ax, ay), (bx, by) in zip(ring, ring[1:] + ring[:1]))) / 2


def _share_check(center: PointInfo, shares: dict[str, float], radius: float) -> tuple[str, str]:
    """Redak za približnu oznaku: koliko kruga oko nje je u građevinskom području (točno, iz obrisa)
    i u kojem je naselju središte (prema bloku PPV-a, npr. "RUKAVAC - GRAĐEVINSKO PODRUČJE").
    Samo postoci, bez ⚠ (odluka korisnika 8. 10.)."""
    inside, other = round(shares.get("naselja", 0) * 100), round(shares.get("izvan naselja", 0) * 100)
    place = center.block.split(" - ")[0].strip().title() if center.block else ""
    parts = [f"{inside} % u građevinskom području naselja"] + ([f"{other} % izvan naselja"] if other else [])
    if inside + other < 100:
        parts.append("ostatak izvan građevinskog područja" if inside + other else "ostatak izvan")
    return (f"🗺 Krug {radius:.0f} m oko približne oznake na karti{f' ({place})' if place else ''}: "
            f"{', '.join(parts)} – ISPU; točnu česticu provjeri"), ""


def _gp_check(info: PointInfo, where: str, caveat: str, house: bool, use: str) -> LandCheck:
    if info.gp == "naselja":
        part = " (neizgrađeni dio)" if "NEIZGRAĐENI" in info.use.upper() else \
            " (izgrađeni dio)" if "IZGRAĐENI" in info.use.upper() else ""
        return LandCheck(f"🗺 U građevinskom području naselja{part} – ISPU, prema {where}", info=info)
    if info.gp == "izvan naselja":
        why = "kuća je u zoni druge namjene (dogradnja i obnova po pravilima te zone)" if house else "nije za obiteljsku kuću"
        return LandCheck(f"🗺 Građevinsko područje IZVAN naselja – ISPU, prema {where}",
                         f"građevinsko područje izvan naselja ({use or 'izdvojena namjena'}) – {why}, provjeri{caveat}", info)
    if house:
        return LandCheck(f"🗺 NIJE u građevinskom području – ISPU, prema {where}",
                         f"prema ISPU-u kuća nije u građevinskom području{f' ({use})' if use else ''} – dogradnja i "
                         f"zamjenska gradnja su ograničene, provjeri legalnost{caveat}", info)
    return LandCheck(f"🗺 NIJE u građevinskom području – ISPU, prema {where}",
                     f"prema ISPU-u nije u građevinskom području{f' ({use})' if use else ''} – provjeri{caveat}", info)


def gp_text(info: PointInfo) -> str:
    if info.gp == "naselja":
        part = " (neizgrađeni dio)" if "NEIZGRAĐENI" in info.use.upper() else \
            " (izgrađeni dio)" if "IZGRAĐENI" in info.use.upper() else ""
        return f"u građevinskom području naselja{part}"
    if info.gp == "izvan naselja":
        return "građevinsko područje IZVAN naselja"
    return "NIJE u građevinskom području"
