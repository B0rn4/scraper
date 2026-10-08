"""Šalje stanje s Redmija (redmi.db, sažeto u redmi.db.gz) na granu state-redmi na GitHubu.

GitHub iz toga zna da Redmi radi (inače šalje mail) i uključuje Njuškalo u tjedni
izvještaj. Grana uvijek ima samo jednu verziju datoteke (kao grana state). Sažeto jer se
šalje svakih 20 minuta (baza je oko 5 puta manja)."""

import gzip
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = "B0rn4/scraper"
BRANCH = "state-redmi"


def main() -> int:
    db = Path(sys.argv[1] if len(sys.argv) > 1 else Path.home() / "redmi.db")
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not db.exists():
        print(f"redmi_sync: nema {db}")
        return 0
    if not token:
        print("redmi_sync: nema GITHUB_TOKEN u ~/.scraper.env")
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        # Kopija kroz SQLite (backup), ne kopiranje datoteke: prekinuto pokretanje može ostaviti
        # redmi.db-journal, koji SQLite pri čitanju vrati, a goli primjerak datoteke ne.
        copy = Path(tmp) / "kopija.db"
        src, dst = sqlite3.connect(db), sqlite3.connect(copy)
        src.backup(dst)
        src.close()
        dst.close()
        (Path(tmp) / "redmi.db.gz").write_bytes(gzip.compress(copy.read_bytes(), mtime=0))
        copy.unlink()
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        run = lambda *args: subprocess.run(["git", *args], cwd=tmp, env=env, capture_output=True, text=True)  # noqa: E731
        run("init", "-q")
        run("checkout", "-q", "-b", BRANCH)
        run("add", "redmi.db.gz")
        run("-c", "user.name=Redmi", "-c", "user.email=redmi@users.noreply.github.com", "commit", "-qm", "Stanje s Redmija")
        result = run("push", "-qf", f"https://x-access-token:{token}@github.com/{REPO}.git", BRANCH)
    if result.returncode != 0:
        print("redmi_sync: slanje nije uspjelo:", result.stderr.replace(token, "***")[:300])
        return 1
    print("redmi_sync: stanje poslano")
    return 0


if __name__ == "__main__":
    sys.exit(main())
