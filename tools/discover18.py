"""Osamnaesti krug: katastarska čestica → lokacija preko javnih servisa DGU-a
(INSPIRE katastarske čestice WFS/WMS, OSS). Za oglase koji navode k.č. i k.o."""

import json
import re
import sys
import time
import traceback
from pathlib import Path
from urllib.parse import urljoin

from curl_cffi import requests as cffi

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "debug-out") / "discovery18"
BASES = ["https://api.uredjenazemlja.hr/services/inspire/cp/wfs", "https://api.uredjenazemlja.hr/services/inspire/cp_wfs/wfs",
         "https://api.uredjenazemlja.hr/services/inspire/cp_wms/wms", "https://api.uredjenazemlja.hr/services/inspire/cp/ows"]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {}
    s = cffi.Session(impersonate="chrome")
    try:
        caps = {}
        for base in BASES:
            for service in ("WFS", "WMS"):
                try:
                    r = s.get(base, params={"service": service, "request": "GetCapabilities"}, timeout=60)
                    names = re.findall(r"<(?:\w+:)?Name>([^<]+)</(?:\w+:)?Name>", r.text)
                    caps[f"{base}:{service}"] = {"status": r.status_code, "bytes": len(r.text), "names": names[:20],
                                                 "formats": re.findall(r"<(?:\w+:)?Format>([^<]+)</(?:\w+:)?Format>", r.text)[:15],
                                                 "head": r.text[:200]}
                    if r.status_code == 200 and len(r.text) > 500:
                        (OUT / f"caps_{base.rsplit('/', 2)[-2]}_{service}.xml").write_text(r.text[:400000], encoding="utf-8")
                except Exception as exc:  # noqa: BLE001
                    caps[f"{base}:{service}"] = {"error": str(exc)[:200]}
        summary["caps"] = caps
        # WFS GetFeature: čestica 1000 u k.o. 315958 (Omišalj) – razni oblici filtra.
        tries = {}
        for base in BASES[:2] + BASES[3:]:
            for type_name in ("cp:CadastralParcel", "CP.CadastralParcel", "CadastralParcel"):
                for flt in (None, "label='1000'", "nationalCadastralReference LIKE '315958%'"):
                    params = {"service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": type_name,
                              "count": 2, "outputFormat": "application/json"}
                    if flt:
                        params["CQL_FILTER"] = flt
                    else:
                        params["bbox"] = "345000,5000000,346000,5001000,urn:ogc:def:crs:EPSG::3765"
                    try:
                        r = s.get(base, params=params, timeout=60)
                        tries[f"{base}|{type_name}|{flt}"] = {"status": r.status_code, "body": r.text[:700]}
                    except Exception as exc:  # noqa: BLE001
                        tries[f"{base}|{type_name}|{flt}"] = {"error": str(exc)[:200]}
                    time.sleep(0.3)
        summary["wfs_getfeature"] = tries
        # OSS (Zajednički informacijski sustav): skripte → API adrese za čestice.
        oss = {}
        try:
            r = s.get("https://oss.uredjenazemlja.hr/", timeout=60)
            oss["status"] = r.status_code
            scripts = re.findall(r'<script[^>]+src="([^"]+)"', r.text)
            paths = set()
            for src in scripts[:15]:
                body = s.get(urljoin("https://oss.uredjenazemlja.hr/", src), timeout=60).text
                paths |= set(re.findall(r'["\'`](/?(?:oss/)?public/[\w\-/]*(?:parcel|cestic|cad)[\w\-/]*)', body, re.I))
            oss["paths"] = sorted(paths)[:80]
        except Exception as exc:  # noqa: BLE001
            oss["error"] = str(exc)[:300]
        summary["oss"] = oss
    except Exception:  # noqa: BLE001
        summary["error"] = traceback.format_exc()[-3000:]
    (OUT / "sazetak.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
