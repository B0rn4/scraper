"""Pravi preglednik (Chromium preko Playwrighta) za portale koji odbijaju obične zahtjeve.

Koristi se samo na Redmiju (Njuškalo). Profil preglednika je trajan, pa kolačići
zaštite ostaju između pokretanja, kao kod običnog posjetitelja. Playwright se
uvozi tek kad se preglednik zaista pokrene (na GitHubu nije instaliran)."""

import time
from pathlib import Path

PROFILE = Path.home() / ".njuskalo-profil"
USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/131.0.0.0 Safari/537.36")


class BrowserError(Exception):
    pass


class Browser:
    def __init__(self, profile: Path = PROFILE, delay: float = 8.0):
        self.profile = profile
        self.delay = delay  # razmak između stranica, kao kad čovjek klikne dalje
        self._pw = None
        self._ctx = None
        self._last = 0.0

    def _start(self):
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        options = dict(headless=True, locale="hr-HR", user_agent=USER_AGENT, viewport={"width": 1366, "height": 900},
                       args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"])
        try:  # "novi" način rada bez prozora teže je prepoznati
            self._ctx = self._pw.chromium.launch_persistent_context(str(self.profile), channel="chromium", **options)
        except Exception:  # noqa: BLE001
            self._ctx = self._pw.chromium.launch_persistent_context(str(self.profile), **options)

    def get(self, url: str, wait_selector: str = "body") -> str:
        if self._ctx is None:
            self._start()
        wait = self.delay - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        page = self._ctx.new_page()
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=60000)
            try:
                page.wait_for_selector(wait_selector, timeout=20000)
            except Exception:  # noqa: BLE001 – provjera sadržaja slijedi niže
                pass
            html = page.content()
            status = resp.status if resp else None
        finally:
            page.close()
            self._last = time.monotonic()
        if status and status >= 400:
            raise BrowserError(f"HTTP {status} za {url}")
        return html

    def close(self) -> None:
        if self._ctx is not None:
            self._ctx.close()
            self._pw.stop()
            self._ctx = self._pw = None
