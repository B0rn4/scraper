"""Razvoj: što ISPU zna o točki osim građevinskog područja i PPV-a – slojevi prostornih
planova (namjena, zone, transformirani planovi), zone zaštite kulturnih dobara.

    python tools/ispu_istrazi.py IZLAZ

Zapiše cijeli katalog slojeva (katalog.json) i odgovore identify za nekoliko točaka sa
svim slojevima čiji put spominje planove, namjenu, zone, zaštitu ili PPV (tocke.json)."""

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.ispu import API, HEADERS, Ispu, to_htrs  # noqa: E402

POINTS = {
    "Njivice, središte": (45.1636, 14.5517),
    "Krk, stara jezgra": (45.0270, 14.5752),
    "Malinska, naselje": (45.1246, 14.5280),
    "Opatija, centar": (45.3376, 14.3076),
    "Vrbnik, jezgra": (45.0763, 14.6744),
    "Kostrena, Sv. Lucija": (45.3086, 14.4934),
    "Kastav (transformiran plan)": (45.3725, 14.3487),
}
WANT = re.compile(r"plan|namjen|zon|za[sš]tit|kultur|PPV|urban|transform|uvjet|gradnj", re.I)


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    ispu = Ispu()
    found: list[dict] = []
    ispu._walk(ispu.session.get(API + "gis/catalog-izbornik", timeout=60).json(), [], found)
    (out / "katalog.json").write_text(json.dumps(found, ensure_ascii=False, indent=1), encoding="utf-8")
    layers = [la for la in found if la.get("hashIdentify") and WANT.search(la["_path"] + " " + la["label"].get("hr", ""))]
    print(f"katalog: {len(found)} slojeva, za identify {len(layers)}")
    results = {}
    for name, (lat, lon) in POINTS.items():
        x, y = to_htrs(lat, lon)
        answers = []
        for i in range(0, len(layers), 15):          # po 15 slojeva: veliki upiti ISPU odbija
            chunk = [{k: v for k, v in la.items() if not k.startswith("_")} for la in layers[i:i + 15]]
            try:
                r = ispu.session.post(API + "gis/identify", json={"x": x, "y": y, "scale": 2000, "layers": chunk},
                                      headers=HEADERS, timeout=60)
                answers.append({"od": i, "status": r.status_code,
                                "odgovor": r.json() if r.status_code < 400 else r.text[:500]})
            except Exception as exc:  # noqa: BLE001
                answers.append({"od": i, "greska": f"{type(exc).__name__}: {exc}"})
            time.sleep(1.2)
        results[name] = answers
        print(name, [a.get("status") for a in answers])
    (out / "tocke.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
