"""Ručna provjera lokacije oglasa u ISPU-u (građevinsko područje, PPV, kulturna dobra).

Pokreće GitHub (radnja "Planovi", naredba "lokacija"), jer okruženje za razvoj ne dolazi do
portala ni do ISPU-a; rezultat ide na granu debug (planovi/lokacije/).

    python tools/provjeri_lokaciju.py IZLAZ ADRESA_OGLASA|LAT,LON [...]

Za adresu oglasa koordinate i vrsta oznake ("marker": točna, "only_area": približna) čitaju se
iz podataka stranice (nekretnine.hr, index.hr: __NEXT_DATA__ / JSON u stranici)."""

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.http import Http  # noqa: E402
from scraper.ispu import RING_M, Ispu, _ring_check, gp_text  # noqa: E402

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


def main() -> int:
    out_dir, args = Path(sys.argv[1]), sys.argv[2:]
    http, ispu, results = Http(), Ispu(), []
    for arg in args:
        try:
            item = locate(http, arg)
            if "lat" in item:
                center = ispu.point(item["lat"], item["lon"])
                item["sredina"] = {"gp": gp_text(center), "namjena": center.use, "blok": center.block,
                                   "ppv_gradevinsko": center.land_values,
                                   "kulturna_dobra": [h.describe() for h in center.heritage]}
                ring = ispu.gp_around(item["lat"], item["lon"])
                item["krug_m"], item["krug"] = RING_M, ring
                item["redak"], item["upozorenje"] = _ring_check(ring)
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
