"""Devetnaesti krug: brzina upita DGU INSPIRE WFS za česticu (različiti filtri)."""

import json
import sys
import time
from pathlib import Path

from curl_cffi import requests as cffi

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "debug-out") / "discovery19"
WFS = "https://api.uredjenazemlja.hr/services/inspire/cp/wfs"
FILTERS = [
    "label='354/12' AND nationalCadastralReference LIKE '315958-%'",
    "nationalCadastralReference='315958-354/12'",
    "label='354/12'",
    "nationalCadastralReference LIKE '315958-354/12'",
    "inspireId.localId LIKE 'CP.%' AND label='354/12' AND nationalCadastralReference LIKE '315958%'",
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    s = cffi.Session(impersonate="chrome")
    out = {}
    for rnd in range(2):
        for flt in FILTERS:
            for fmt in ("application/json",):
                t = time.monotonic()
                try:
                    r = s.get(WFS, params={"service": "WFS", "version": "2.0.0", "request": "GetFeature",
                                           "typeNames": "cp:CadastralParcel", "count": 3, "outputFormat": fmt,
                                           "CQL_FILTER": flt}, timeout=120)
                    feats = r.json().get("features", []) if r.status_code == 200 else []
                    out[f"{rnd}|{flt}"] = {"status": r.status_code, "s": round(time.monotonic() - t, 1),
                                           "n": len(feats), "refs": [f["properties"].get("nationalCadastralReference") for f in feats],
                                           "body": "" if feats else r.text[:300]}
                except Exception as exc:  # noqa: BLE001
                    out[f"{rnd}|{flt}"] = {"error": str(exc)[:150], "s": round(time.monotonic() - t, 1)}
    (OUT / "sazetak.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
