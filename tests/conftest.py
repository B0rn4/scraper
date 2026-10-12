"""Testovi ne idu na mrežu: pravi zahtjev (curl_cffi) odmah ne uspijeva, bez čekanja ponovnih
pokušaja. Inače bi ishod i trajanje ovisili o vanjskim stranicama i o danu – ponedjeljkom npr.
tjedni izvještaj čita odluke o planovima sa sn.pgz.hr i zavod.pgz.hr (12. 10. testovi na GitHubu
nisu stigli završiti u 10 minuta)."""
import time
import types

import pytest


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    import scraper.http as http
    from curl_cffi import requests as cffi

    monkeypatch.setattr(http, "time", types.SimpleNamespace(monotonic=time.monotonic, time=time.time,
                                                            sleep=lambda seconds: None))

    def refuse(self, url, *args, **kwargs):
        raise ConnectionError(f"test bez mreže: {url}")

    monkeypatch.setattr(cffi.Session, "get", refuse)
    monkeypatch.setattr(cffi.Session, "post", refuse)
