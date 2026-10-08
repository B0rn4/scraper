"""Preuzima s grane state (GitHub) ono što Redmi treba prije pokretanja: sažetak već
viđenih oglasa, medijane cijena i github.json (zadnje pokretanje, "Ne zanima me").
Nema li redmi.db (ponovna instalacija), vraća ga s grane state-redmi – inače bi prvo
pokretanje poslalo praznu bazu preko stare (poslane poruke, 👎 na stare poruke).

Preko GitHub API-ja, ne raw.githubusercontent.com: raw adresa do 5 minuta vraća staro
stanje, a Redmi kreće 10 minuta nakon GitHuba baš da vidi njegovo najnovije stanje.
Ako API ne odgovori, pokušava se raw adresa. Datoteka koja se ne preuzme ostaje stara."""

import gzip
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = "B0rn4/scraper"
FILES = ("seen.json.gz", "cijene.json", "github.json")


def _get(url: str, headers: dict) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as resp:
        return resp.read()


def main() -> int:
    home = Path(sys.argv[1] if len(sys.argv) > 1 else Path.home())
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    api_headers = {"Accept": "application/vnd.github.raw", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        api_headers["Authorization"] = f"Bearer {token}"
    failed = 0
    for name in FILES:
        try:
            try:
                data = _get(f"https://api.github.com/repos/{REPO}/contents/{name}?ref=state", api_headers)
            except Exception:  # noqa: BLE001 – rezerva: raw adresa (možda malo starija)
                data = _get(f"https://raw.githubusercontent.com/{REPO}/state/{name}", {})
            tmp = home / f"{name}.tmp"
            tmp.write_bytes(data)
            tmp.replace(home / name)
        except Exception as exc:  # noqa: BLE001
            print(f"redmi_preuzmi: {name} nije preuzet ({type(exc).__name__}: {str(exc).replace(token, '***') if token else exc})")
            failed += 1
    db = home / "redmi.db"
    if not db.exists():
        for name in ("redmi.db.gz", "redmi.db"):
            try:
                data = _get(f"https://api.github.com/repos/{REPO}/contents/{name}?ref=state-redmi", api_headers)
                tmp = home / "redmi.db.tmp"
                tmp.write_bytes(gzip.decompress(data) if name.endswith(".gz") else data)
                tmp.replace(db)
                print(f"redmi_preuzmi: redmi.db vraćen s GitHuba ({db.stat().st_size} B)")
                break
            except urllib.error.HTTPError as exc:
                if exc.code != 404:          # 404: nema te datoteke ni grane – prvo postavljanje
                    print(f"redmi_preuzmi: redmi.db nije vraćen (HTTP {exc.code})")
                    return 2
            except Exception as exc:  # noqa: BLE001 – mreža: ne smije se poslati prazna baza preko stare
                print(f"redmi_preuzmi: redmi.db nije vraćen ({type(exc).__name__})")
                return 2
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
