"""Šesnaesti krug: proba scraper/ispu.py na stvarnim oglasima.
- slojevi (građevinsko područje, najnoviji PPV zemljišta) iz kataloga;
- točke (poznate lokacije);
- FINA: čestice iz opisa → k.o. → oblik čestice → građevinsko područje;
- nekretnine.hr zemljišta s oznakom na karti → građevinsko područje.
Opisi se ne spremaju (javna grana); samo k.o., broj čestice i rezultat."""

import json
import sys
import time
import traceback
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.http import Http  # noqa: E402
from scraper.ispu import Ispu, check_land, parcels_in_text  # noqa: E402
from scraper.locations import Locator  # noqa: E402
from scraper.models import LAND  # noqa: E402
from scraper.runner import load_config  # noqa: E402
from scraper.sources.base import INCREMENTAL  # noqa: E402
from scraper.sources.fina import Fina  # noqa: E402
from scraper.sources.nekretnine_hr import NekretnineHr  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "debug-out") / "discovery16"
POINTS = {"krk_centar": (45.0272, 14.5753), "brzac_suma": (45.0875, 14.5900), "njivice_hotel": (45.1655, 14.5480)}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {"started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        ispu = Ispu()
        summary["layers"] = [{"label": la["label"]["hr"], "id": la["id"], "layers": la["layers"]} for la in ispu.layers()]
        summary["points"] = {k: asdict(ispu.point(*v)) for k, v in POINTS.items()}
        names = {"omisalj": "Omišalj", "njivice": "Njivice", "krk": "Krk"}
        summary["checks"] = {t: asdict(check_land(ispu, t, None, None, True, names)) for t in (
            "Zemljište k.č. 354/12 k.o. Omišalj", "Zemljište kčbr. 354/12, K.O. OMISALJ", "k.č. 99999/9 k.o. Omišalj")}

        cfg, loc = load_config(), Locator()
        http = Http(delay=1.0)
        fina = []
        try:
            for x in Fina(http, loc, cfg["kriteriji"]).fetch(INCREMENTAL, set())[:40]:
                if x.kind != LAND:
                    continue
                for ko, kc in parcels_in_text(x.description)[:2]:
                    item = {"ko": ko, "kc": kc}
                    try:
                        found = ispu.parcel(ko, kc)
                        item["found"] = found
                        if found:
                            item["gp"] = asdict(ispu.identify(found["x"], found["y"]))
                    except Exception as exc:  # noqa: BLE001
                        item["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
                    fina.append(item)
                    time.sleep(0.5)
                if len(fina) >= 12:
                    break
        except Exception:  # noqa: BLE001
            summary["fina_error"] = traceback.format_exc()[-1500:]
        summary["fina"] = fina

        nek = []
        try:
            src = NekretnineHr(http, loc, cfg["kriteriji"])
            items = [x for x in src.fetch(INCREMENTAL, set()) if x.kind == LAND and x.extra.get("lat")]
            summary["nekretnine_land_with_coords"] = len(items)
            for x in items[:12]:
                item = {"title": x.title[:80], "approx": x.extra.get("priblizna_lokacija"),
                        "parcels": parcels_in_text(x.description)}
                if not x.extra.get("priblizna_lokacija"):
                    item["gp"] = asdict(ispu.point(x.extra["lat"], x.extra["lon"]))
                nek.append(item)
                time.sleep(0.5)
        except Exception:  # noqa: BLE001
            summary["nekretnine_error"] = traceback.format_exc()[-1500:]
        summary["nekretnine"] = nek
    except Exception:  # noqa: BLE001
        summary["error"] = traceback.format_exc()[-3000:]
    finally:
        summary["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        (OUT / "sazetak.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
