"""Mjerenje GoHomea: kašnjenje i pokrivenost u odnosu na portale koje pratimo izravno
(index.hr, oglasnik.hr – imaju datum objave), broj Njuškalo oglasa bez ograničenja
stranica, filtri u upitu (cijena, izvor) i ima li Realitice."""

import gzip
import json
import re
import sys
import time
import traceback
from collections import Counter
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.http import Http  # noqa: E402
from scraper.locations import Locator  # noqa: E402
from scraper.models import HOUSE, LAND  # noqa: E402
from scraper.runner import load_config  # noqa: E402
from scraper.sources.base import INCREMENTAL  # noqa: E402
from scraper.sources.gohome import BASE, _query_name, parse_page  # noqa: E402
from scraper.sources.index_oglasi import IndexOglasi  # noqa: E402
from scraper.sources.oglasnik import Oglasnik  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "debug-out") / "discovery9"
COUNT = re.compile(r"pronađeno\s+([\d\s]+?)\s+nekretnina")
DEADLINE = time.monotonic() + 17 * 60


def save(name, data):
    (OUT / name).write_bytes(gzip.compress(json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8")))


def gohome_query(http, q, max_pages=15):
    items, count, pages = [], None, 0
    for page in range(1, max_pages + 1):
        if time.monotonic() > DEADLINE:
            break
        url = f"{BASE}?q={quote(q, encoding='iso-8859-2')}" + (f"&str={page}" if page > 1 else "")
        text = http.get(url).content.decode("iso-8859-2", "replace")
        pages = page
        if count is None:
            m = COUNT.search(text)
            count = int(re.sub(r"\s", "", m.group(1))) if m else None
        got = parse_page(text, HOUSE)
        items += [{"id": x.source_id, "domain": x.extra.get("izvor"), "url": x.url, "indexed": x.published,
                   "name": x.title, "kind": x.kind, "sub": x.subtype, "price": x.price} for x in got]
        if not got or f"str={page + 1}" not in text:
            break
    return {"q": q, "count": count, "pages": pages, "items": items}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {"started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    http = Http(delay=1.5)
    locator = Locator()
    cfg = load_config()
    jls = [j.name for j in locator.jls.values() if j.included]

    # 1) Portali s datumom objave: najnoviji oglasi (kao redovno pokretanje).
    for cls in (IndexOglasi, Oglasnik):
        try:
            src = cls(http, locator, cfg["kriteriji"])
            got = src.fetch(INCREMENTAL, set())
            save(f"{src.name}.json.gz", [{"id": x.source_id, "url": x.url, "published": x.published, "kind": x.kind,
                                          "municipality": x.municipality, "title": x.title} for x in got])
            summary[src.name] = len(got)
        except Exception as exc:  # noqa: BLE001
            summary[cls.name] = f"greška: {exc}"[:300]
            traceback.print_exc()

    # 2) Probni upiti: filtri u upitu, izvor, "Najnovije", Realitica.
    probes = [
        "kuca krk prodaja Najnovije",
        "kuca rijeka prodaja Najnovije",
        "kuca krk prodaja Zadnjih 7 dana",
        "kuca krk prodaja do 400000 eura Zadnjih 7 dana",
        "kuca krk prodaja njuskalo",
        "kuca krk prodaja njuskalo.hr Zadnjih 7 dana",
        "kuca rijeka prodaja realitica",
        "realitica",
        "kuca primorsko-goranska prodaja Zadnjih 7 dana",
    ]
    probe_out = []
    for q in probes:
        try:
            r = gohome_query(http, q, max_pages=2)
            r["domains"] = Counter(i["domain"] for i in r["items"]).most_common()
            r["dates"] = Counter(i["indexed"] for i in r["items"]).most_common()
            probe_out.append(r)
        except Exception as exc:  # noqa: BLE001
            probe_out.append({"q": q, "error": str(exc)[:300]})
    save("probes.json.gz", probe_out)
    summary["probes"] = [{k: v for k, v in p.items() if k != "items"} for p in probe_out]

    # 3) Svih 15 JLS, zadnjih 7 dana, bez ograničenja stranica (do 15).
    full = []
    for word in ("kuca", "gradevinsko zemljiste"):
        for name in jls:
            q = f"{word} {_query_name(name)} prodaja Zadnjih 7 dana"
            try:
                full.append(gohome_query(http, q))
            except Exception as exc:  # noqa: BLE001
                full.append({"q": q, "error": str(exc)[:300]})
    save("gohome_7dana.json.gz", full)
    summary["gohome_7dana"] = [{"q": r["q"], "count": r.get("count"), "pages": r.get("pages"),
                                "n": len(r.get("items", [])), "error": r.get("error"),
                                "domains": Counter(i["domain"] for i in r.get("items", [])).most_common(6)}
                               for r in full]

    # 4) Realitica izravno (u fazi 0 vraćala je 403 s GitHuba).
    try:
        r = http.session.get("https://www.realitica.com/", timeout=20)
        summary["realitica"] = {"status": r.status_code, "title": re.findall(r"<title>([^<]*)", r.text)[:1]}
    except Exception as exc:  # noqa: BLE001
        summary["realitica"] = {"error": str(exc)[:300]}

    summary["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
