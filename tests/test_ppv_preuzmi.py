import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import ppv_preuzmi  # noqa: E402


class Resp:
    def __init__(self, features):
        self.status_code, self.headers, self.text = 200, {"content-type": "application/json"}, ""
        self._f = features

    def json(self):
        return {"features": self._f}


class Session:
    """Blokovi su točke na mreži od 500 m; vraća one u pravokutniku iz BBOX-a."""
    def __init__(self, cap):
        self.cap, self.calls = cap, []

    def get(self, url, params=None, **kw):
        x0, y0, x1, y1 = map(float, params["BBOX"].split(","))
        self.calls.append((x0, y0, x1, y1))
        feats = [{"id": f"b.{x}.{y}", "properties": {"cb_naziv": f"B {x} {y}"},
                  "geometry": {"type": "Polygon", "coordinates": [[[x, y], [x + 10, y], [x, y + 10], [x, y]]]}}
                 for x in range(0, 8000, 500) for y in range(0, 8000, 500) if x0 <= x < x1 and y0 <= y < y1]
        return Resp(feats[:self.cap])


def test_tiles_cover_settlements():
    t = ppv_preuzmi.tiles([{"lat": 45.1636, "lon": 14.5517}])
    assert 4 <= len(t) <= 9 and len(set(t)) == len(t)


def test_collect_splits_when_answer_is_full(monkeypatch):
    monkeypatch.setattr(ppv_preuzmi, "FEATURE_COUNT", 40)
    monkeypatch.setattr(ppv_preuzmi.time, "sleep", lambda s: None)
    layer = {"hash": "h", "servis": "9", "layers": "404", "geoserver": "Cjenovni_blok_PPV_2025"}
    session, found = Session(cap=40), {}
    n = ppv_preuzmi.collect(session, layer, (0, 0, 4000, 4000), found)
    assert len(found) == 64 and n == 5                   # 64 bloka > 40: jedan upit + četiri četvrtine
    assert abs(found["b.500.500"]["_x"] - 503) <= 1 and session.calls[0] == (0, 0, 4000, 4000)
