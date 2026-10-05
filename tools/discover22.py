"""Dvadeset drugi krug (faza 4): probno čitanje natječaja sa svih stranica iz
data/natjecaji.yaml (scraper/tenders.py), bez slanja."""

import json
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.http import Http  # noqa: E402
from scraper.ispu import parcels_in_text  # noqa: E402
from scraper.locations import Locator  # noqa: E402
from scraper.tenders import Reader, details, load_sites  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "debug-out") / "discovery22"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    reader = Reader(Http(delay=1.5), Locator())
    summary = {}
    for site in load_sites():
        t0 = time.monotonic()
        try:
            items = reader.fetch(site)
            out = []
            for t in items[:12]:
                if len(out) < 4:
                    reader.load_text(t)
                out.append({"title": t.title[:160], "url": t.url, "published": t.published, "jls": t.jls,
                            "text_len": len(t.text), "details": details(t.text) if t.text else None,
                            "parcels": parcels_in_text(t.text)[:4] if t.text else None, "extra": t.extra})
            summary[site["naziv"]] = {"n": len(items), "s": round(time.monotonic() - t0, 1), "items": out}
        except Exception:  # noqa: BLE001
            summary[site["naziv"]] = {"error": traceback.format_exc()[-1200:]}
        (OUT / "sazetak.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
