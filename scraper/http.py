"""HTTP s pristojnim razmakom između zahtjeva i ponovnim pokušajima."""

import re
import time
from urllib.parse import urlparse

from curl_cffi import requests as cffi


class FetchError(RuntimeError):
    pass


_BLOCKED = re.compile(r"just a moment|attention required|access denied|checking your browser|ddos|captcha"
                      r"|service unavailable|maintenance|privremeno nedostupn|u izradi", re.I)


def blocked(text: str) -> str:
    """Stranica zaštite od robota ili održavanja koju poslužitelj vrati s HTTP 200 ("Just a
    moment…"): njezin naslov, inače prazno. Takva stranica nije "nema ničeg novog"."""
    head = (text or "")[:50000]
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", head)
    title = " ".join(m.group(1).split())[:100] if m else ""
    # Ne "challenge-platform": Cloudflare tu skriptu ubacuje i u obične stranice.
    if _BLOCKED.search(title) or "_cf_chl_opt" in head:
        return title or "zaštita od robota"
    return ""


class Http:
    def __init__(self, delay: float = 2.0, retries: int = 2, timeout: int = 40):
        self.session = cffi.Session(impersonate="chrome")
        self.delay = delay
        self.retries = retries
        self.timeout = timeout
        self._last: dict[str, float] = {}
        self.requests = 0

    def get(self, url: str, retries: int | None = None, timeout: float | None = None, **kwargs):
        host = urlparse(url).netloc
        error = None
        for attempt in range((self.retries if retries is None else retries) + 1):
            wait = self.delay - (time.monotonic() - self._last.get(host, 0))
            if wait > 0:
                time.sleep(wait)
            self._last[host] = time.monotonic()
            self.requests += 1
            try:
                resp = self.session.get(url, timeout=timeout or self.timeout, **kwargs)
            except Exception as exc:  # noqa: BLE001 – mrežne greške se ponavljaju
                error = f"{type(exc).__name__}: {exc}"
            else:
                if resp.status_code < 500 and resp.status_code != 429:
                    if resp.status_code >= 400:
                        raise FetchError(f"HTTP {resp.status_code} za {url}")
                    return resp
                error = f"HTTP {resp.status_code}"
            time.sleep(5 * (attempt + 1))
        raise FetchError(f"{error} za {url}")
