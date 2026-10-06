"""Trideset prvi krug: Rijekin natječaj za zemljišta (stranica bez datuma) – tekst, rok,
čestice, cijene; i nove Rijekine stranice (stanovi/poslovni, ostali natječaji)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper import tenders  # noqa: E402
from scraper.http import Http  # noqa: E402
from scraper.locations import Locator  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "debug-out") / "discovery31"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    reader = tenders.Reader(Http(delay=1.5), Locator())
    out = {}
    for site in tenders.load_sites():
        if not site["naziv"].startswith("Grad Rijeka ("):
            continue
        try:
            items = reader.fetch(site)
        except Exception as exc:  # noqa: BLE001
            out[site["naziv"]] = str(exc)[:300]
            continue
        rows = []
        for t in items[:6]:
            reader.load_text(t)
            found = tenders.lots(t.text)
            rows.append({"title": t.title, "url": t.url, "published": t.published, "extra": t.extra,
                         "info": tenders.details(t.text), "lots": [(x.label, x.price, x.ppm, x.area, x.house) for x in found[:10]],
                         "text": t.text[:6000]})
        out[site["naziv"]] = rows
    (OUT / "rijeka.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
