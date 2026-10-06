"""Trideset osmi krug: ISPU identify sa slojevima građevinskog područja, PPV-a i
zaštićenih kulturnih dobara (Z- i P-lista Ministarstva kulture) zajedno – radi li
pouzdano, koliko traje, što vraća u povijesnim jezgrama, kod pojedinačnih dobara i
na običnim lokacijama."""

import json
import re
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.ispu import API, HEADERS, Ispu, parse_identify, to_htrs  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "debug-out") / "discovery38"
POINTS = [("Krk, stara jezgra", 45.0266, 14.5755), ("Vrbnik, jezgra", 45.0756, 14.6744),
          ("Kastav, jezgra", 45.3757, 14.3487), ("Volosko", 45.3505, 14.3185), ("Opatija, centar", 45.3376, 14.3058),
          ("Opatija, Villa Angiolina", 45.33693, 14.30766), ("Lovran, stari grad", 45.2918, 14.2741),
          ("Bakar, jezgra", 45.3060, 14.5340), ("Omišalj, jezgra", 45.2106, 14.5520), ("Dobrinj, jezgra", 45.1360, 14.6060),
          ("Baška, stari dio", 44.9696, 14.7556), ("Trsat, gradina", 45.3316, 14.4560), ("Rijeka, Korzo", 45.3271, 14.4422),
          ("Kraljevica, Nova Kraljevica", 45.2716, 14.5683), ("Malinska, nova kuća", 45.1180, 14.5370),
          ("Kostrena, kuće", 45.3105, 14.4950), ("Dramalj", 45.1950, 14.6620)]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ispu = Ispu()
    out = {"layers": {}, "points": {}}
    try:
        found = []
        ispu._walk(ispu.session.get(API + "gis/catalog-izbornik", timeout=40).json(), [], found)
        base = ispu.layers()
        heritage = [la for la in found if "Nepokretna kulturna dobra po statusu zaštite" in la["_path"] and la["hashIdentify"]]
        out["layers"] = {"base": [la["label"]["hr"] for la in base], "heritage": [la["_path"] for la in heritage]}
        variants = {"gp_ppv": base, "gp_ppv_bastina": base + heritage, "bastina": heritage}
        for label, lat, lon in POINTS:
            x, y = to_htrs(lat, lon)
            res = {}
            for name, layers in variants.items():
                for attempt in (1, 2):
                    body = {"x": x, "y": y, "scale": 2000,
                            "layers": [{k: v for k, v in la.items() if not k.startswith("_")} for la in layers]}
                    t = time.monotonic()
                    try:
                        r = ispu.session.post(API + "gis/identify", json=body, headers=HEADERS, timeout=40)
                        data = r.json()
                        ok = isinstance(data, list)
                        names = []
                        if ok:
                            for layer in data:
                                for item in layer.get("items") or []:
                                    f = {(i.get("label") or {}).get("hr", ""): i.get("value") for i in item.get("items") or []}
                                    if "Registarski broj" in f:
                                        names.append({k: f.get(k) for k in ("Naziv", "Vrsta", "Klasifikacija", "Registarski broj",
                                                                            "Status zaštite", "Zona", "Adresa")})
                            info = parse_identify(data)
                            summary = {"gp": info.gp, "use": info.use, "ppv": info.land_values[:3]}
                        else:
                            summary = {"error": str(data)[:300]}
                        res[f"{name}#{attempt}"] = {"status": r.status_code, "ok": ok, "s": round(time.monotonic() - t, 2),
                                                    "info": summary, "heritage": names,
                                                    "labels": [la.get("label", {}).get("hr") for la in data] if ok else []}
                    except Exception as exc:  # noqa: BLE001
                        res[f"{name}#{attempt}"] = {"error": str(exc)[:300]}
                    time.sleep(0.7)
            out["points"][label] = res
            (OUT / "rezultati.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:  # noqa: BLE001
        out["error"] = traceback.format_exc()[-1500:]
    (OUT / "rezultati.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
