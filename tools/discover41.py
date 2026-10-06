"""Četrdeset prvi krug: stvarna provjera check_land (kuća) s novim slojevima kulturnih
dobara – točna i približna oznaka, u staroj jezgri Krka i izvan nje."""

import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.ispu import Ispu, check_land  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "debug-out") / "discovery41"
CASES = [("Krk jezgra, točno", "Kamena kuća u staroj gradskoj jezgri", 45.0266, 14.5755, False),
         ("Krk jezgra, približno, opis jezgre", "Kamena kuća u staroj gradskoj jezgri", 45.0266, 14.5755, True),
         ("Krk jezgra, približno, bez opisa", "Kuća s pogledom", 45.0266, 14.5755, True),
         ("Opatija centar, točno", "Kuća", 45.3376, 14.3058, False),
         ("Malinska polje, točno", "Kuća", 45.1180, 14.5370, False),
         ("Kostrena, točno", "Kuća", 45.3105, 14.4950, False)]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ispu, out = Ispu(), {}
    for label, text, lat, lon, approx in CASES:
        try:
            r = check_land(ispu, text, lat, lon, approx, house=True)
            out[label] = {"line": r.line, "warning": r.warning, "heritage": r.heritage}
        except Exception:  # noqa: BLE001
            out[label] = {"error": traceback.format_exc()[-800:]}
    (OUT / "rezultati.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
