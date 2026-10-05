"""Dvadeseti krug: stranica oglasa na nekretnine.hr (puni opis, značajke – garaža,
parking, okućnica). Sprema samo strukturu i kratke isječke (javna grana)."""

import json
import re
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.http import Http  # noqa: E402
from scraper.locations import Locator  # noqa: E402
from scraper.models import HOUSE  # noqa: E402
from scraper.runner import load_config  # noqa: E402
from scraper.sources.base import INCREMENTAL  # noqa: E402
from scraper.sources.nekretnine_hr import NekretnineHr  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "debug-out") / "discovery20"


def walk(o, path, out, depth=0):
    if depth > 9:
        return
    if isinstance(o, dict):
        for k, v in o.items():
            if k in ("translations", "seo", "breadcrumbs", "footer", "header", "messages"):
                continue
            walk(v, f"{path}.{k}", out, depth + 1)
    elif isinstance(o, list):
        for i, v in enumerate(o[:3]):
            walk(v, f"{path}[{i}]", out, depth + 1)
    else:
        out.append((path, str(o)[:160] + (f" …[{len(str(o))} znakova]" if len(str(o)) > 160 else "")))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {}
    try:
        http = Http(delay=1.5)
        src = NekretnineHr(http, Locator(), load_config()["kriteriji"])
        items = [x for x in src.fetch(INCREMENTAL, set()) if x.kind == HOUSE][:2]
        pages = []
        for x in items:
            r = http.get(x.url)
            html = r.text
            m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
            item = {"url": x.url, "status": r.status_code, "bytes": len(html), "list_desc_len": len(x.description),
                    "next_data": bool(m)}
            if m:
                data = json.loads(m.group(1))
                flat = []
                walk(data, "", flat)
                item["paths"] = [f"{p} = {v}" for p, v in flat if re.search(
                    r"descr|feature|garag|park|box|surface|garden|land|caption|primary|secondary|ga4|energy|year|cond|location|latitude", p, re.I)][:300]
                desc = [v for p, v in flat if p.endswith(".description")]
                item["desc_sample_len"] = [len(d) for d in desc][:5]
            pages.append(item)
        summary["pages"] = pages
    except Exception:  # noqa: BLE001
        summary["error"] = traceback.format_exc()[-3000:]
    (OUT / "sazetak.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
