"""Dvadeset šesti krug: probne poruke za natječaje s novim detaljima (čestica, početna
cijena po m², PPV na lokaciji, medijan traženih, sažeti redak, odluke naselja) na
stvarnim objavama – ništa se ne šalje, poruke se spremaju za pregled."""

import json
import sys
import time
import traceback
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper import tenders  # noqa: E402
from scraper.models import REJECT, WARN  # noqa: E402
from scraper.prices import AskingPrices  # noqa: E402
from scraper.runner import Runner  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "debug-out") / "discovery26"
PRICES_URL = "https://raw.githubusercontent.com/B0rn4/scraper/state/cijene.json"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    runner = Runner(OUT / "s.db", OUT, send=False)
    prices = None
    try:
        (OUT / "cijene.json").write_bytes(requests.get(PRICES_URL, timeout=30).content)
        prices = AskingPrices.from_file(OUT / "cijene.json", runner.locator)
    except Exception as exc:  # noqa: BLE001
        print("cijene.json:", exc)
    reader = tenders.Reader(runner.http, runner.locator)
    since = (date.today() - timedelta(days=200)).isoformat()
    messages, rows = [], []
    deadline = time.monotonic() + 900
    for site in tenders.load_sites():
        try:
            items = reader.fetch(site)
        except Exception as exc:  # noqa: BLE001
            rows.append({"site": site["naziv"], "error": str(exc)[:300]})
            continue
        for t in items[:8]:
            try:
                reader.load_text(t)
                info = tenders.details(t.text) if t.text else {}
                published = t.published or t.extra.get("datum_iz_teksta", "")
                if published and published < since and not (info.get("rok") and info["rok"] >= date.today().isoformat()):
                    continue
                found = tenders.lots(t.text)
                jls = t.jls if t.jls and runner.locator.by_name(t.jls) else ""
                where = tenders.place_text(t, found)
                verdict = runner.locator.settlement_verdict(jls, "", tenders.place_text(t, found, False)) if jls else None
                by_ko = runner.locator.settlement_verdict(jls, "", where) if jls else None
                if by_ko and by_ko != verdict and not (verdict and verdict[0] == REJECT):
                    note = " (prema k.o. – katastarska općina može obuhvaćati više naselja)" if by_ko[0] == REJECT else ""
                    verdict = (WARN, f"{by_ko[1]}{note}")
                rows.append({"site": site["naziv"], "title": t.title, "url": t.url, "published": published, "info": info,
                             "verdict": verdict, "lots": [{k: v for k, v in asdict(x).items() if k != "context"} for x in found],
                             "text": t.text[:2500]})
                if verdict and verdict[0] == REJECT:
                    messages.append(f"=== BEZ PORUKE ({verdict[1]}) {t.url}")
                    continue
                text = runner._tender_message(t, info, found, jls, where, verdict, prices, deadline)
                messages.append(f"=== {t.url}\n{text}")
                rows[-1]["lots_after"] = [{k: v for k, v in asdict(x).items() if k != "context"} for x in found]
            except Exception:  # noqa: BLE001
                rows.append({"site": site["naziv"], "title": t.title, "error": traceback.format_exc()[-1200:]})
        (OUT / "poruke.txt").write_text("\n\n".join(messages), encoding="utf-8")
        (OUT / "natjecaji.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (OUT / "s.db").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
