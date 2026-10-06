"""Trideset sedmi krug: skripte Geoportala kulturnih dobara (konfiguracija karte, slojevi,
identifikacija, pretraga po čestici i adresi) – spremaju se za čitanje adresa servisa."""

import json
import re
import sys
import time
from pathlib import Path

from curl_cffi import requests as cffi

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "debug-out") / "discovery37"
GEO = "https://geoportal.kulturnadobra.hr/"
FILES = ["app/scripts/app.js", "app/scripts/configs/geoportal/mapConfig.js", "app/scripts/services/geoportal/mapService.js",
         "app/scripts/services/geoportal/layersService.js", "app/scripts/services/geoportal/tools/identifyTool.js",
         "app/scripts/directives/identifyCulturalProperty.js", "app/scripts/directives/identifyPopup.js",
         "app/scripts/services/geoportal/advancedSearchService.js", "app/scripts/services/geoportal/geometrySearchService.js",
         "app/scripts/services/geoportal/appService.js", "app/scripts/services/geoportal/layerGroupsService.js",
         "app/scripts/services/geoportal/layersUtilService.js", "app/scripts/services/geoportal/shareLinkService.js",
         "app/scripts/directives/search/attributeSearch.js", "app/scripts/directives/search/spatialSearch.js",
         "app/scripts/services/welcome/searchService.js",
         "app/scripts/controllers/welcome/culturalHeritageSearchByParcelController.js",
         "app/scripts/controllers/welcome/culturalHeritageSearchByAddressController.js",
         "app/scripts/controllers/welcome/searchResultController.js", "app/scripts/directives/welcome/initWelcomePage.js"]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    s = cffi.Session(impersonate="chrome")
    summary = {}
    for f in FILES:
        try:
            r = s.get(GEO + f, timeout=40)
            (OUT / f.replace("/", "__")).write_text(r.text, encoding="utf-8")
            summary[f] = {"status": r.status_code, "bytes": len(r.text),
                          "urls": sorted(set(re.findall(r"""["'`]((?:https?:)?//[^"'`]+|/?(?:api|Api|geoserver|wms|ows)[^"'`]*)["'`]""", r.text)))[:60]}
        except Exception as exc:  # noqa: BLE001
            summary[f] = {"error": str(exc)[:200]}
        time.sleep(0.5)
    (OUT / "sazetak.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
