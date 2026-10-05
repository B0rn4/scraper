"""Sedamnaesti krug: ISPU traženje katastarske općine i čestice (velika/mala slova)."""

import json
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.ispu import API, HEADERS, Ispu, wkt_centroid  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "debug-out") / "discovery17"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {}
    try:
        ispu = Ispu()
        s = ispu.session
        s.get("https://ispu.mgipu.hr/", timeout=30)
        s.get(API + "auth/authz", timeout=30)
        ko = {}
        for word in ("Njivice", "NJIVICE", "njivice", "NJIV", "KRK", "OMIŠALJ", "OMISALJ", "DOBRINJ", "VRH"):
            for headers in ({}, HEADERS):
                r = s.get(API + "gis/search-kat-opcina", params={"input": word}, headers=headers, timeout=30)
                ko[f"{word}:{bool(headers)}"] = {"status": r.status_code, "body": r.text[:600]}
                time.sleep(0.3)
        summary["search_ko"] = ko
        r = s.get(API + "gis/search-text", params={"input": "NJIVICE"}, headers=HEADERS, timeout=30)
        summary["search_text"] = {"status": r.status_code, "body": r.text[:2500]}
        mbr = None
        for v in ko.values():
            try:
                data = json.loads(v["body"])
                if data:
                    mbr = data[0].get("maticniBroj")
                    break
            except ValueError:
                pass
        summary["mbr"] = mbr
        kc = {}
        if mbr:
            for label in ("1", "10", "100", "1000", "1000/1", "2000"):
                r = s.get(API + "gis/info-lokacija-kat-cestica", params={"labela": label, "maticniBroj": mbr},
                          headers=HEADERS, timeout=30)
                kc[label] = {"status": r.status_code, "body": r.text[:400], "centroid": wkt_centroid(r.text)}
                time.sleep(0.3)
        summary["kat_cestica"] = kc
    except Exception:  # noqa: BLE001
        summary["error"] = traceback.format_exc()[-3000:]
    (OUT / "sazetak.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
