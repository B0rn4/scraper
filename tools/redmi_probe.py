"""Faza 2b – proba na Redmiju: prolaze li Njuškalo i Realitica s kućne IP adrese.

Pokreće se u Ubuntuu unutar Termuxa, u mapi scraper (upute u REDMI.md):

    python tools/redmi_probe.py                   # Njuškalo i Realitica bez preglednika (curl_cffi)
    python tools/redmi_probe.py --samo-realitica  # samo Realitica (Njuškalo se ne dira)
    python tools/redmi_probe.py --provjeri-preglednik  # radi li Chromium (otvara Realiticu, ne Njuškalo)
    python tools/redmi_probe.py --playwright      # Njuškalo pravim preglednikom (Chromium)
    python tools/redmi_probe.py --njuskalo-oglas  # po jedan oglas kuće i zemljišta s Njuškala (Chromium)
    python tools/redmi_probe.py --posalji         # samo ponovno pošalji spremljene rezultate
    python tools/redmi_probe.py --spremi URL [URL …]  # spremi navedene stranice Njuškala (Chromium)

Ispisuje kratak sažetak, sprema uzorke stranica u redmi-out/ (naziv počinje vremenom
probe, pa se ništa ne prepisuje) i šalje ih na granu debug (mapa redmi/) preko GitHub
API-ja. Token se upisuje kad skripta pita; ne sprema se nigdje.

Njuškalo štiti ShieldSquare (Radware): prvi zahtjevi bez preglednika prolaze, a nakon
nekoliko uzastopnih dolazi stranica "ShieldSquare Captcha". Zato se Njuškalu šalje
najviše jedan zahtjev po kategoriji, s razmakom."""

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
PROFILE = Path.home() / ".njuskalo-profil"  # kolačići preglednika ostaju između pokretanja
REPO = "B0rn4/scraper"
BRANCH = "debug"
STAMP = time.strftime("%m%d-%H%M")

NJUSKALO = {
    "njuskalo_kuce": "https://www.njuskalo.hr/prodaja-kuca/primorsko-goranska?sort=new",
    "njuskalo_zemljista": "https://www.njuskalo.hr/prodaja-zemljista/primorsko-goranska?sort=new",
}
REALITICA = "https://www.realitica.com"
REALITICA_PAGES = {
    "realitica_kuce": f"{REALITICA}/index.php?for=Prodaja&pZpa=Primorje-Gorski+Kotar&pState=Hrvatska"
                      "&type%5B%5D=Home&qob=p-new&lng=hr",
    "realitica_gradevinska": f"{REALITICA}/index.php?for=Prodaja&pZpa=Primorje-Gorski+Kotar&pState=Hrvatska"
                             "&type%5B%5D=Residential_lot&qob=p-new&lng=hr",
    "realitica_regija": f"{REALITICA}/nekretnine/Primorje-Gorski%20Kotar/",
}
LISTING = re.compile(r'href="((?:https://www\.realitica\.com)?/(?:hr/)?listing/\d+)"')
CHROME_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
             "Chrome/131.0.0.0 Safari/537.36")


def analyse(name: str, status, body: bytes, seconds: float) -> dict:
    text = body.decode("utf-8", "replace")
    title = (re.findall(r"<title[^>]*>\s*([^<]{0,120})", text) or [""])[0].strip()
    info = {"status": status, "kB": round(len(body) / 1024), "s": round(seconds, 1), "title": title}
    if name.startswith("njuskalo"):
        info["oglasa"] = text.count("EntityList-item--Regular") + text.count("EntityList-item--VauVau")
        info["captcha"] = "captcha" in title.lower()
    else:
        info["oglasa"] = len(set(LISTING.findall(text)))
        m = re.search(r"od ukupno(?:&nbsp;|\s|<[^>]+>)*([\d.]+)", text)
        info["ukupno"] = m.group(1) if m else None
    return info


def passed(name: str, info: dict) -> bool:
    if info.get("status") != 200 or info.get("captcha"):
        return False
    return info["oglasa"] > 0 or name.endswith("_oglas")


def save(name: str, body: bytes) -> None:
    OUT.mkdir(exist_ok=True)
    (OUT / f"{STAMP}_{name}.html.gz").write_bytes(gzip.compress(body))


def fetch_cffi(url: str):
    from curl_cffi import requests as cffi

    t = time.monotonic()
    r = cffi.get(url, impersonate="chrome", timeout=40, headers={"Accept-Language": "hr-HR,hr;q=0.9,en;q=0.8"})
    return r.status_code, r.content, time.monotonic() - t


class Browser:
    """Chromium s trajnim profilom: kolačići zaštite ostaju kao kod običnog posjetitelja."""

    def __init__(self):
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        options = dict(headless=True, locale="hr-HR", user_agent=CHROME_UA, viewport={"width": 1366, "height": 900},
                       args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"])
        try:  # "novi" headless način je teže prepoznati
            self.ctx = self._pw.chromium.launch_persistent_context(str(PROFILE), channel="chromium", **options)
        except Exception:  # noqa: BLE001
            self.ctx = self._pw.chromium.launch_persistent_context(str(PROFILE), **options)

    def fetch(self, url: str, wait_selector: str):
        t = time.monotonic()
        page = self.ctx.new_page()
        resp = page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_selector(wait_selector, timeout=20000)
        except Exception:  # noqa: BLE001 – stranica se svejedno sprema
            pass
        body = page.content().encode("utf-8")
        page.close()
        return (resp.status if resp else None), body, time.monotonic() - t

    def close(self):
        self.ctx.close()
        self._pw.stop()


def probe(name: str, url: str, fetch, label: str, results: dict, pause: float) -> bytes | None:
    key = f"{name} [{label}]"
    try:
        status, body, seconds = fetch(url)
    except Exception as exc:  # noqa: BLE001
        results[key] = {"greška": f"{type(exc).__name__}: {exc}"[:300]}
        print(f"  {key}: greška – {type(exc).__name__}: {str(exc)[:150]}")
        return None
    info = analyse(name, status, body, seconds)
    results[key] = info
    save(f"{name}__{label}", body)
    print(f"  {key}: {'PROLAZI' if passed(name, info) else 'NE PROLAZI'} – {info}")
    time.sleep(pause)
    return body if passed(name, info) else None


def run_njuskalo(results: dict, use_playwright: bool) -> None:
    print("Njuškalo:")
    if use_playwright:
        browser = Browser()
        try:
            for name, url in NJUSKALO.items():
                probe(name, url, lambda u: browser.fetch(u, "li.EntityList-item"), "playwright", results, 20)
        finally:
            browser.close()
    else:
        for name, url in NJUSKALO.items():
            probe(name, url, fetch_cffi, "chrome", results, 20)


def run_njuskalo_ads(results: dict) -> None:
    """Otvara prvi oglas s već spremljenih popisa (popisi se ne učitavaju ponovno)."""
    print("Njuškalo, pojedinačni oglasi:")
    targets = {}
    for kind in ("kuce", "zemljista"):
        lists = sorted(OUT.glob(f"*_njuskalo_{kind}__playwright.html.gz"))
        if not lists:
            print(f"  nema spremljenog popisa ({kind}); prvo pokreni --playwright")
            continue
        text = gzip.decompress(lists[-1].read_bytes()).decode("utf-8", "replace")
        m = re.search(r'EntityList-item--Regular[^"]*"><!--\[--><article[^>]*><h3 class="entity-title"><a href="([^"]+)"', text)
        if m:
            targets[f"njuskalo_{kind}_oglas"] = "https://www.njuskalo.hr" + m.group(1)
    if not targets:
        return
    browser = Browser()
    try:
        for name, url in targets.items():
            probe(name, url, lambda u: browser.fetch(u, "h1"), "playwright", results, 15)
    finally:
        browser.close()


def run_saved_pages(results: dict, urls: list[str]) -> None:
    """Sprema navedene stranice (npr. neobične oglase za testove), s razmakom između njih."""
    print("Njuškalo, zadane stranice:")
    browser = Browser()
    try:
        for i, url in enumerate(urls, 1):
            m = re.search(r"oglas-(\d+)", url)
            name = f"njuskalo_oglas_{m.group(1)}" if m else f"njuskalo_stranica_{i}"
            probe(name, url, lambda u: browser.fetch(u, "h1"), "playwright", results, 15)
    finally:
        browser.close()


def run_realitica(results: dict) -> None:
    print("Realitica:")
    first = None
    for name, url in REALITICA_PAGES.items():
        body = probe(name, url, fetch_cffi, "chrome", results, 4)
        if body and not first:
            links = LISTING.findall(body.decode("utf-8", "replace"))
            first = links[0] if links else None
    if first:
        probe("realitica_oglas", urljoin(REALITICA, first), fetch_cffi, "chrome", results, 0)


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


def _env_token() -> str:
    """Token iz ~/.scraper.env (isti koji koristi redmi_sync), da ga ne treba lijepiti."""
    env = Path.home() / ".scraper.env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.strip().startswith("GITHUB_TOKEN="):
                return line.split("=", 1)[1].strip().strip("\"'")
    return ""


def send() -> None:
    sent_log = OUT / ".poslano"
    sent = set(sent_log.read_text().split()) if sent_log.exists() else set()
    files = {p.name: p.read_bytes() for p in sorted(OUT.glob("*sazetak*.json")) + sorted(OUT.glob("*.html.gz"))
             if p.name not in sent}
    if not files:
        print("Nema novih rezultata za slanje.")
        return
    token = os.environ.get("GITHUB_TOKEN") or _env_token() or getpass.getpass(
        "Zalijepi GitHub token za slanje rezultata (ne prikazuje se; Enter = ne šalji): ").strip()
    if not token:
        print("Ništa nije poslano. Kasnije pošalji s: python tools/redmi_probe.py --posalji")
        return
    try:
        failed = upload(token, files)
    except Exception as exc:  # noqa: BLE001
        print(f"  slanje nije uspjelo: {type(exc).__name__}: {exc}")
        failed = len(files)
    if failed:
        print(f"\nSLANJE NIJE USPJELO ({failed} od {len(files)} datoteka). Pošalji mi snimku zaslona;"
              " kad popravimo, ponovi s: python tools/redmi_probe.py --posalji")
    else:
        sent_log.write_text("\n".join(sorted(sent | set(files))))
        print("\nGotovo, rezultati su poslani. Javi mi.")


def main() -> None:
    args = set(sys.argv[1:])
    if "--posalji" in args:
        send()
        return
    urls = [a for a in sys.argv[1:] if a.startswith("http")]
    results = {"vrijeme": time.strftime("%Y-%m-%d %H:%M:%S"), "python": sys.version.split()[0],
               "sustav": platform.platform(), "argumenti": sorted(args)}
    if "--spremi" in args:
        if not urls:
            print("Iza --spremi navedi adrese stranica.")
            return
        run_saved_pages(results, urls)
    elif "--njuskalo-oglas" in args:
        run_njuskalo_ads(results)
    elif "--provjeri-preglednik" in args:
        print("Chromium:")
        browser = Browser()
        try:
            probe("realitica_naslovnica", f"{REALITICA}/", lambda u: browser.fetch(u, "body"), "playwright", results, 0)
        finally:
            browser.close()
    elif "--samo-realitica" not in args:
        run_njuskalo(results, "--playwright" in args)
    if not args & {"--playwright", "--provjeri-preglednik", "--njuskalo-oglas", "--spremi"}:
        run_realitica(results)
    OUT.mkdir(exist_ok=True)
    (OUT / f"{STAMP}_sazetak.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\nRezultati su spremljeni u redmi-out/.")
    send()


if __name__ == "__main__":
    main()
