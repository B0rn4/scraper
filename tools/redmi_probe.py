"""Faza 2b – proba na Redmiju: prolaze li Njuškalo i Realitica s kućne IP adrese.

Pokreće se u Ubuntuu unutar Termuxa, u mapi scraper (upute u REDMI.md):

    python tools/redmi_probe.py               # curl_cffi (bez preglednika)
    python tools/redmi_probe.py --playwright  # pravi preglednik, ako curl_cffi ne prolazi
    python tools/redmi_probe.py --posalji     # samo ponovno pošalji već spremljene rezultate

Ispisuje kratak sažetak, sprema uzorke stranica u redmi-out/ i šalje ih na granu
debug (mapa redmi/) preko GitHub API-ja. Token se upisuje kad skripta pita;
ne sprema se nigdje. Po izvoru se šalje svega nekoliko zahtjeva, s razmakom."""

import base64
import getpass
import gzip
import json
import os
import platform
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

OUT = Path("redmi-out")
REPO = "B0rn4/scraper"
BRANCH = "debug"

NJUSKALO = {
    "njuskalo_kuce": "https://www.njuskalo.hr/prodaja-kuca/primorsko-goranska?sort=new",
    "njuskalo_zemljista": "https://www.njuskalo.hr/prodaja-zemljista/primorsko-goranska?sort=new",
}
REALITICA_HOME = "https://www.realitica.com/"
REALITICA_GUESSES = {
    "realitica_trazi": "https://www.realitica.com/?cur_page=0&for=Prodaja&pZpa=Primorsko-Goranska"
                       "&pState=Hrvatska&type%5B%5D=Home&lng=hr",
}
BLOCK_MARKERS = ["captcha", "shieldsquare", "radware", "perfdrive", "px-captcha", "access denied",
                 "cf-chl", "request unsuccessful", "the request could not be satisfied", "are you a robot",
                 "potvrdite da niste robot"]


def analyse(name: str, status, body: bytes, seconds: float) -> dict:
    text = body.decode("utf-8", "replace")
    low = text.lower()
    info = {
        "status": status,
        "kB": round(len(body) / 1024),
        "s": round(seconds, 1),
        "title": (re.findall(r"<title[^>]*>\s*([^<]{0,120})", text) or [""])[0].strip(),
        "blokada": [m for m in BLOCK_MARKERS if m in low],
    }
    if name.startswith("njuskalo"):
        info["oglasa"] = text.count("EntityList-item--Regular") + text.count("EntityList-item--VauVau")
        info["next_data"] = "__NEXT_DATA__" in text
    else:
        info["poveznica_na_oglas"] = len(set(re.findall(r'href="([^"]*/listing/\d+[^"]*)"', text)))
    return info


def ok(info: dict) -> bool:
    if info.get("status") != 200 or info["blokada"]:
        return False
    return info.get("oglasa", 1) > 0 if "oglasa" in info else info["kB"] > 5


def save(name: str, body: bytes) -> None:
    OUT.mkdir(exist_ok=True)
    (OUT / f"{name}.html.gz").write_bytes(gzip.compress(body))


def fetch_cffi(url: str, impersonate: str):
    from curl_cffi import requests as cffi

    t = time.monotonic()
    r = cffi.get(url, impersonate=impersonate, timeout=40,
                 headers={"Accept-Language": "hr-HR,hr;q=0.9,en;q=0.8"})
    return r.status_code, r.content, time.monotonic() - t


def fetch_playwright(url: str, wait_selector: str | None):
    from playwright.sync_api import sync_playwright

    t = time.monotonic()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = browser.new_page(locale="hr-HR", viewport={"width": 1280, "height": 900})
        resp = page.goto(url, wait_until="domcontentloaded", timeout=60000)
        if wait_selector:
            try:
                page.wait_for_selector(wait_selector, timeout=20000)
            except Exception:  # noqa: BLE001 – stranica se svejedno sprema
                pass
        body = page.content().encode("utf-8")
        status = resp.status if resp else None
        browser.close()
    return status, body, time.monotonic() - t


def try_methods(name: str, url: str, methods: list, results: dict) -> bytes | None:
    """Pokušava redom dok jedan način ne prođe; tako se šalje što manje zahtjeva."""
    for label, fn in methods:
        try:
            status, body, seconds = fn(url)
        except Exception as exc:  # noqa: BLE001
            results[f"{name} [{label}]"] = {"greška": f"{type(exc).__name__}: {exc}"[:300]}
            print(f"  {name} [{label}]: greška – {type(exc).__name__}: {str(exc)[:120]}")
            continue
        info = analyse(name, status, body, seconds)
        results[f"{name} [{label}]"] = info
        save(f"{name}__{label}", body)
        print(f"  {name} [{label}]: {'PROLAZI' if ok(info) else 'NE PROLAZI'} – {info}")
        time.sleep(4)
        if ok(info):
            return body
    return None


def realitica_links(body: bytes) -> dict:
    """Iz naslovnice Realitice: obrasci pretrage, izbor županije i RSS poveznice."""
    text = body.decode("utf-8", "replace")
    forms = re.findall(r"<form[^>]*>", text, re.I)
    selects = {}
    for m in re.finditer(r'<select[^>]*name="([^"]+)"[^>]*>(.*?)</select>', text, re.I | re.S):
        options = re.findall(r'<option[^>]*value="([^"]*)"[^>]*>([^<]*)', m.group(2))
        selects[m.group(1)] = [o for o in options if re.search(r"primorsk|prodaj|kuć|kuc|zemlj|house|land", " ".join(o), re.I)][:15]
    rss = sorted(set(re.findall(r'href="([^"]*rss[^"]*)"', text, re.I)))[:10]
    return {"forms": forms[:5], "selects": selects, "rss": rss}


def upload(token: str, files: dict[str, bytes]) -> int:
    """Vraća broj datoteka koje se nisu dale poslati."""
    import requests

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    r = requests.get(f"https://api.github.com/repos/{REPO}", headers=headers, timeout=30)
    if r.status_code != 200:
        print(f"  GitHub ne prihvaća token: {r.status_code} {r.text[:200]}")
        return len(files)
    if not r.json().get("permissions", {}).get("push"):
        print("  Token nema dozvolu pisanja: na GitHubu u postavkama tokena provjeri da je odabran"
              " repozitorij B0rn4/scraper i Contents: Read and write.")
        return len(files)
    failed = 0
    for name, data in files.items():
        url = f"https://api.github.com/repos/{REPO}/contents/redmi/{name}"
        sha = None
        r = requests.get(url, headers=headers, params={"ref": BRANCH}, timeout=30)
        if r.status_code == 200:
            sha = r.json().get("sha")
        body = {"message": f"Redmi proba: {name}", "branch": BRANCH, "content": base64.b64encode(data).decode()}
        if sha:
            body["sha"] = sha
        r = requests.put(url, headers=headers, json=body, timeout=60)
        if r.status_code in (200, 201):
            print(f"  poslano {name}: u redu")
        else:
            failed += 1
            print(f"  poslano {name}: GREŠKA {r.status_code} {r.text[:200]}")
    return failed


def send(use_playwright: bool) -> None:
    summaries = sorted(OUT.glob("sazetak*.json"))
    if not summaries:
        print("Nema spremljenih rezultata u redmi-out/. Prvo pokreni probu.")
        return
    token = os.environ.get("GITHUB_TOKEN") or getpass.getpass(
        "Zalijepi GitHub token za slanje rezultata (ne prikazuje se; Enter = ne šalji): ").strip()
    if not token:
        print("Ništa nije poslano. Kasnije pošalji s: python tools/redmi_probe.py --posalji")
        return
    files = {p.name: p.read_bytes() for p in summaries}
    files.update({p.name: p.read_bytes() for p in sorted(OUT.glob("*.html.gz"))})
    try:
        failed = upload(token, files)
    except Exception as exc:  # noqa: BLE001
        print(f"  slanje nije uspjelo: {type(exc).__name__}: {exc}")
        failed = len(files)
    if failed:
        print(f"\nSLANJE NIJE USPJELO ({failed} od {len(files)} datoteka). Pošalji mi snimku zaslona;"
              " kad popravimo, ponovi s: python tools/redmi_probe.py --posalji")
    else:
        print("\nGotovo, rezultati su poslani. Javi mi.")


def main() -> None:
    if "--posalji" in sys.argv:
        send(False)
        return
    use_playwright = "--playwright" in sys.argv
    results = {"vrijeme": time.strftime("%Y-%m-%d %H:%M:%S"), "python": sys.version.split()[0],
               "sustav": platform.platform(), "nacin": "playwright" if use_playwright else "curl_cffi"}
    if use_playwright:
        methods = lambda sel: [("playwright", lambda u: fetch_playwright(u, sel))]  # noqa: E731
    else:
        methods = lambda sel: [("chrome", lambda u: fetch_cffi(u, "chrome")),  # noqa: E731
                               ("safari_ios", lambda u: fetch_cffi(u, "safari_ios"))]

    print("Njuškalo:")
    for name, url in NJUSKALO.items():
        try_methods(name, url, methods("li.EntityList-item"), results)

    print("Realitica:")
    home = try_methods("realitica_naslovnica", REALITICA_HOME, methods(None), results)
    if home:
        links = realitica_links(home)
        results["realitica_obrasci"] = links
        targets = dict(REALITICA_GUESSES)
        if links["rss"]:
            targets["realitica_rss"] = urljoin(REALITICA_HOME, links["rss"][0])
        for name, url in targets.items():
            try_methods(name, url, methods(None), results)

    OUT.mkdir(exist_ok=True)
    summary = json.dumps(results, ensure_ascii=False, indent=1).encode("utf-8")
    (OUT / ("sazetak_playwright.json" if use_playwright else "sazetak.json")).write_bytes(summary)
    print("\nRezultati su spremljeni u redmi-out/.")
    send(use_playwright)


if __name__ == "__main__":
    main()
