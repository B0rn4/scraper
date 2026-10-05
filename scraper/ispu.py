"""ISPU (Ministarstvo prostornoga uređenja): podaci za točku na karti.

Isti poziv koji koristi preglednik na ispu.mgipu.hr (POST api/v1/gis/identify), bez
prijave. Koordinate su u HTRS96/TM (EPSG:3765); pretvorba je ovdje, bez dodatnih
biblioteka (radi i na Redmiju). Slojevi se pronalaze po nazivu u katalogu, jer se
brojevi slojeva mijenjaju sa svakim novim PPV-om."""

import math

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
