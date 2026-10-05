"""ISPU (Ministarstvo prostornoga uređenja): podaci za točku ili katastarsku česticu.

Isti pozivi koje koristi preglednik na ispu.mgipu.hr, bez prijave:
- POST api/v1/gis/identify – slojevi na točki (građevinsko područje, PPV zemljišta);
- GET api/v1/gis/search-kat-opcina?input=… – matični broj katastarske općine;
- GET api/v1/gis/info-lokacija-kat-cestica?labela=…&maticniBroj=… – oblik čestice (WKT).
Koordinate su u HTRS96/TM (EPSG:3765); pretvorba je ovdje, bez dodatnih biblioteka
(radi i na Redmiju). Slojevi se pronalaze po nazivu u katalogu, jer se brojevi
slojeva mijenjaju sa svakim novim PPV-om."""

import math
import re
from dataclasses import dataclass, field

from .text import fold

API = "https://ispu.mgipu.hr/api/v1/"
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

    def parcel(self, ko_name: str, kc: str) -> tuple[float, float] | None:
        """Težište čestice (HTRS96) ili None ako k.o. ili čestica nije pronađena."""
        r = self.session.get(API + "gis/search-kat-opcina", params={"input": ko_name}, timeout=self.timeout)
        r.raise_for_status()
        want = fold(ko_name)
        matches = [k for k in r.json() if fold(str(k.get("labela", ""))).split(" (")[0].strip() == want]
        if not matches:
            matches = [k for k in r.json() if fold(str(k.get("labela", ""))).startswith(want)]
        if not matches:
            return None
        r = self.session.get(API + "gis/info-lokacija-kat-cestica",
                             params={"labela": kc, "maticniBroj": matches[0]["maticniBroj"]}, timeout=self.timeout)
        if r.status_code != 200 or not r.text.strip():
            return None
        data = r.json() if r.text.strip().startswith(("{", "[", '"')) else r.text
        wkt = data if isinstance(data, str) else (data.get("wkt") or data.get("geom") or "") if isinstance(data, dict) else ""
        return wkt_centroid(wkt)


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
