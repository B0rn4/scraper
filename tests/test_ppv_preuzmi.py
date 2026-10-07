import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import build_ppv  # noqa: E402
import ppv_preuzmi  # noqa: E402

KML = (Path(__file__).parent / "fixtures" / "ppv_krk.kml").read_text(encoding="utf-8")


class Resp:
    status_code, headers = 200, {"content-type": "application/vnd.google-earth.kml+xml"}
    text = KML


class Session:
    def __init__(self):
        self.calls = []

    def get(self, url, params=None, **kw):
        self.calls.append(params)
        return Resp()


def test_tiles_cover_settlements():
    t = ppv_preuzmi.tiles([{"lat": 45.1636, "lon": 14.5517}])
    assert 4 <= len(t) <= 9 and len(set(t)) == len(t)


def test_kml_blocks_with_values(monkeypatch):
    monkeypatch.setattr(ppv_preuzmi.time, "sleep", lambda s: None)
    layer = {"hash": "h", "servis": "9", "layers": "404", "geoserver": "Cjenovni_blok_PPV_2025"}
    session, found = Session(), {}
    assert ppv_preuzmi.collect(session, layer, (0, 0, 4000, 4000), found) == 2
    assert session.calls[0]["FORMAT"] == "application/vnd.google-earth.kml+xml" and session.calls[0]["LAYERS"] == "404"
    krk = next(b for b in found.values() if b["cb_naziv"] == "KRK - GRAĐEVINSKO 1")
    assert krk["ppv_cb_grop"] == "KRK" and krk["ppv_datum"] == "20260101" and krk["_x"] > 300_000
    assert build_ppv.land_values(krk) == [197.81, 289.93, 190.57]
    sea = next(b for b in found.values() if b["cb_naziv"] == "KRK - MORE I OTOCI")
    assert "ppv_cb_grop" not in sea and build_ppv.land_values(sea) == []
