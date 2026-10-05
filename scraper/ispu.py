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
from dataclasses import dataclass, field

from .text import fmt_m2, fold

API = "https://ispu.mgipu.hr/api/v1/"
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

_KC = re.compile(r"(?:\b(?:z\.?\s*)?k\.?\s*č\.?\s*(?:br\.?|broj)?|\bčkbr\.?|\bkčbr\.?|\bčest(?:ica|ice|ici|\.)\s*(?:br\.?|broj)?)"
                 r"\s*:?\s*(\d{1,5}(?:/\d{1,4})?(?:\s*(?:,|i|te)\s*\d{1,5}(?:/\d{1,4})?)*)", re.I)
_KO = re.compile(r"\b(?i:k\.?\s*o\.?)\s*:?\s+((?:[A-ZČĆŽŠĐ][\wčćžšđČĆŽŠĐ-]*)(?:\s+[A-ZČĆŽŠĐ][\wčćžšđČĆŽŠĐ-]*)*)")


def parcels_in_text(text: str) -> list[tuple[str, str]]:
    """[(katastarska općina, broj čestice)] iz teksta, npr. "k.č. 1234/5, k.o. Njivice".
    Čestica se veže uz najbližu sljedeću (ili prethodnu) oznaku k.o."""
    text = text or ""
    kos = [(m.start(), re.sub(r"(\s+\w)+$", "", m.group(1).strip())) for m in _KO.finditer(text)]
    out = []
    for m in _KC.finditer(text):
        after = [ko for pos, ko in kos if pos >= m.end() and pos - m.end() < 120]
        before = [ko for pos, ko in kos if pos < m.start() and m.start() - pos < 120]
        ko = after[0] if after else (before[-1] if before else "")
        if not ko:
            continue
        for kc in re.split(r"\s*(?:,|\bi\b|\bte\b)\s*", m.group(1)):
            if kc and (ko, kc) not in out:
                out.append((ko, kc))
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


@dataclass
class PointInfo:
    gp: str | None = None          # "naselja", "izvan naselja" ili None (izvan građevinskog područja)
    gp_plan: str = ""              # prostorni plan iz kojeg je granica
    block: str = ""                # cjenovni blok PPV-a
    use: str = ""                  # pretežita namjena bloka, npr. "(GP) IZGRAĐENI DIO GRAĐEVINSKOG PODRUČJA NASELJA"
    land_values: list[float] = field(default_factory=list)   # PPV građevinskog zemljišta stambene/mješovite namjene
    ppv_label: str = ""


class Ispu:
    def __init__(self, session=None, timeout: int = 30):
        if session is None:
            from curl_cffi import requests as cffi
            session = cffi.Session(impersonate="chrome")
        self.session = session
        self.timeout = timeout
        self._layers: list[dict] | None = None
        self.parcels_off = False         # DGU nije odgovorio: do kraja pokretanja bez traženja čestica

    def layers(self) -> list[dict]:
        """Slojevi građevinskog područja i najnoviji PPV zemljišta iz kataloga."""
        if self._layers is None:
            found: list[dict] = []
            self._walk(self.session.get(API + "gis/catalog-izbornik", timeout=self.timeout).json(), [], found)
            gp = [la for la in found if "Građevinska područja" in la["_path"] and la["hashIdentify"]]
            ppv = [la for la in found if re.match(r"PPV 1\.1\.\d{4}\. – zemljišta", la["label"].get("hr", ""))]
            ppv.sort(key=lambda la: la["label"]["hr"], reverse=True)
            self._layers = gp + ppv[:1]
        return self._layers

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
        body = {"x": x, "y": y, "scale": 2000,
                "layers": [{k: v for k, v in la.items() if not k.startswith("_")} for la in self.layers()]}
        r = self.session.post(API + "gis/identify", json=body, headers=HEADERS, timeout=self.timeout)
        r.raise_for_status()
        return parse_identify(r.json())

    def point(self, lat: float, lon: float) -> PointInfo:
        return self.identify(*to_htrs(lat, lon))

    def parcel(self, ko_name: str, kc: str, names: dict[str, str] | None = None) -> dict | None:
        """Točka unutar čestice (HTRS96) i površina: {"x", "y", "povrsina"} ili None.
        K.o. → matični broj iz ISPU-a; čestica iz javnog katastarskog servisa DGU-a
        (INSPIRE). names: normalizirani naziv → naziv s dijakriticima (pretraga ISPU-a
        traži dijakritike: "OMIŠALJ", ne "OMISALJ")."""
        if self.parcels_off:
            return None
        mbr = self.cadastral_municipality(ko_name)
        if mbr is None and names and fold(ko_name) in names:
            mbr = self.cadastral_municipality(names[fold(ko_name)])
        if mbr is None:
            return None
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
        labela je "URED, K.O." (npr. "KRK, OMIŠALJ")."""
        r = self.session.get(API + "gis/search-kat-opcina", params={"input": ko_name.upper()}, timeout=self.timeout)
        r.raise_for_status()
        want = fold(ko_name)
        names = [(k, fold(str(k.get("labela", "")).split(",")[-1])) for k in r.json() or []]
        matches = [k for k, name in names if name == want] or [k for k, name in names if name.startswith(want)]
        # Isti naziv k.o. postoji u više županija (npr. Vrh): prednost uredima u PGŽ-u.
        matches.sort(key=lambda k: fold(str(k.get("labela", "")).split(",")[0]) not in PGZ_OFFICES)
        return matches[0]["maticniBroj"] if matches else None


def parse_identify(data) -> PointInfo:
    info = PointInfo()
    for layer in data if isinstance(data, list) else (data or {}).get("data") or []:
        label = (layer.get("label") or {}).get("hr", "")
        for item in layer.get("items") or []:
            fields = [((x.get("label") or {}).get("hr", ""), x.get("value") or "") for x in item.get("items") or []]
            if label.startswith("Građevinsko područje"):
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


def check_land(ispu: "Ispu", text: str, lat: float | None, lon: float | None, approximate: bool,
               names: dict[str, str] | None = None) -> LandCheck:
    """Je li zemljište u građevinskom području: prvo po katastarskoj čestici iz teksta
    (točno), inače po oznaci na karti oglasa (ako portal kaže da nije približna)."""
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
        why = "čestica iz oglasa nije pronađena u katastru" if parcels else "oglas nema točnu lokaciju ni broj čestice"
        return LandCheck(f"🗺 Građevinsko područje: nije provjereno – {why}")
    caveat = " (oznaka može biti približna)" if where.startswith("oznaci") else ""
    use = info.use.split(") ", 1)[-1].capitalize() if info.use else ""
    if info.gp == "naselja":
        part = " (neizgrađeni dio)" if "NEIZGRAĐENI" in info.use.upper() else \
            " (izgrađeni dio)" if "IZGRAĐENI" in info.use.upper() else ""
        return LandCheck(f"🗺 U građevinskom području naselja{part} – ISPU, prema {where}", info=info)
    if info.gp == "izvan naselja":
        return LandCheck(f"🗺 Građevinsko područje IZVAN naselja – ISPU, prema {where}",
                         f"građevinsko područje izvan naselja ({use or 'izdvojena namjena'}) – nije za obiteljsku kuću, "
                         f"provjeri{caveat}", info)
    return LandCheck(f"🗺 NIJE u građevinskom području – ISPU, prema {where}",
                     f"prema ISPU-u nije u građevinskom području{f' ({use})' if use else ''} – provjeri{caveat}", info)
