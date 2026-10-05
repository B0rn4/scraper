"""Šalje stanje s Redmija (redmi.db) na granu state-redmi na GitHubu.

GitHub iz toga zna da Redmi radi (inače šalje mail) i uključuje Njuškalo u tjedni
izvještaj. Grana uvijek ima samo jednu verziju datoteke (kao grana state)."""

import os
import shutil
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
        shutil.copy(db, Path(tmp) / "redmi.db")
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        run = lambda *args: subprocess.run(["git", *args], cwd=tmp, env=env, capture_output=True, text=True)  # noqa: E731
        run("init", "-q")
        run("checkout", "-q", "-b", BRANCH)
        run("add", "redmi.db")
        run("-c", "user.name=Redmi", "-c", "user.email=redmi@users.noreply.github.com", "commit", "-qm", "Stanje s Redmija")
        result = run("push", "-qf", f"https://x-access-token:{token}@github.com/{REPO}.git", BRANCH)
    if result.returncode != 0:
        print("redmi_sync: slanje nije uspjelo:", result.stderr.replace(token, "***")[:300])
        return 1
    print("redmi_sync: stanje poslano")
    return 0


if __name__ == "__main__":
    sys.exit(main())
