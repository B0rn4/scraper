"""HTTP: ponovni pokušaji i zaštita od robota (bez mreže: odgovori su lažni)."""

import pytest

from scraper.http import FetchError, Http


class Resp:
    def __init__(self, status, cookie=""):
        self.status_code = status
        self.headers = {"set-cookie": cookie} if cookie else {}
        self.text = ""


class Session:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), 0

    def get(self, url, **kwargs):
        self.calls += 1
        return self.responses.pop(0)


def http_with(*responses, retries=2):
    http = Http(delay=0, retries=retries)
    http.session = Session(*responses)
    return http


def test_bot_protection_cookie_from_first_403_lets_second_request_through():
    """5. 11.: nekretnine.hr (DataDome) prvom zahtjevu nove sesije vrati 403 i kolačić; isti zahtjev
    s kolačićem prolazi (proba s GitHuba). Jednom ponovno, i kad ponovnih pokušaja nema (retries=0)."""
    ok = Resp(200)
    http = http_with(Resp(403, "datadome=abc; Path=/"), ok, retries=0)
    assert http.get("https://www.nekretnine.hr/prodaja/") is ok and http.session.calls == 2

    http = http_with(Resp(403, "datadome=abc"), Resp(403, "datadome=def"))
    with pytest.raises(FetchError, match="HTTP 403"):
        http.get("https://www.nekretnine.hr/prodaja/")
    assert http.session.calls == 2                 # samo jednom: stalni 403 je prava greška

    http = http_with(Resp(403), Resp(200))
    with pytest.raises(FetchError, match="HTTP 403"):
        http.get("https://x.hr/")
    assert http.session.calls == 1                 # 403 bez kolačića: odmah greška, kao prije


def test_server_errors_are_retried_as_before():
    http = http_with(Resp(500), Resp(503), retries=1)
    with pytest.raises(FetchError, match="HTTP 503"):
        http.get("https://x.hr/")
    assert http.session.calls == 2
    ok = Resp(200)
    assert http_with(Resp(429), ok).get("https://x.hr/") is ok
