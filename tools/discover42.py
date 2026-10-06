"""Četrdeset drugi krug: zašto ISPU identify ponekad vraća 400 s kulturnim dobrima –
isti upiti brzo zaredom i s razmakom, sa i bez slojeva baštine, uz tijelo odgovora."""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.ispu import API, HEADERS, Ispu, to_htrs  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "debug-out") / "discovery42"
POINTS = [("Krk", 45.0266, 14.5755), ("Malinska", 45.1180, 14.5370), ("Opatija", 45.3376, 14.3058),
          ("Kostrena", 45.3105, 14.4950)]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ispu = Ispu()
    layers = ispu.layers()
    base = [la for la in layers if "kulturna dobra" not in la["_path"]]
    heritage = [la for la in layers if "kulturna dobra" in la["_path"]]
    out = {"layers": [la["_path"][-60:] for la in layers], "calls": []}
    for pause in (0, 1.0):
        for rnd in range(3):
            for name, lat, lon in POINTS:
                for variant, ls in (("sve", layers), ("bez_bastine", base), ("bastina", heritage)):
                    x, y = to_htrs(lat, lon)
                    body = {"x": x, "y": y, "scale": 2000, "layers": [{k: v for k, v in la.items() if not k.startswith("_")} for la in ls]}
                    t = time.monotonic()
                    r = ispu.session.post(API + "gis/identify", json=body, headers=HEADERS, timeout=40)
                    out["calls"].append({"pause": pause, "round": rnd, "point": name, "variant": variant, "status": r.status_code,
                                         "s": round(time.monotonic() - t, 2),
                                         "body": r.text[:300] if r.status_code != 200 else ""})
                    time.sleep(pause)
    (OUT / "rezultati.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
