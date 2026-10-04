"""Za razvoj: sažetak pregleda (JSON) za granu debug. Opisi FINA predmeta se ne
izvoze jer repozitorij je javan."""

import json
import sys
from pathlib import Path

src, dst = Path(sys.argv[1]), Path(sys.argv[2])
dst.mkdir(parents=True, exist_ok=True)
for path in sorted(src.glob("*.json")):
    data = json.loads(path.read_text(encoding="utf-8"))
    for e in data.get("entries", []):
        if e.get("s") == "FINA Očevidnik":
            e["d"] = ""
    (dst / path.name).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"Izvezeno: {[p.name for p in dst.iterdir()]}")
