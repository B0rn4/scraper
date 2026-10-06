import json
from datetime import datetime

import pytest

from scraper.locations import Locator
from scraper.models import HOUSE, LAND, WARN, Decision, Listing
from scraper.notify import format_listing
from scraper.prices import MIN_N, AskingPrices, place_of

NOW = datetime(2026, 10, 5, 12, 0)


@pytest.fixture(scope="module")
def loc():
    return Locator()


def rows(n, jls, title, ppm, kind=HOUSE, area=100, reasons="[]", last_seen="2026-10-01T10:00:00"):
    # Različite cijene (isti oglas se broji jednom), simetrično oko ppm × površina.
    return [{"kind": kind, "jls": jls, "price": ppm * area + 2000 * (i - (n - 1) / 2), "area": area, "title": title,
             "settlement": "", "reasons": reasons, "last_seen": last_seen} for i in range(n)]


def test_place_of(loc):
    assert place_of(loc, "Omišalj", "Kuća u Njivicama s pogledom", "") == "njivice"
    assert place_of(loc, "Krk", "Kuća, Krk", "") == ""          # naziv grada nije naselje
    assert place_of(loc, "Omišalj", "Kuća", "Njivice") == "njivice"


def test_settlement_median_when_enough_listings(loc):
    data = rows(MIN_N, "Omišalj", "Kuća Njivice", 4000) + rows(MIN_N, "Omišalj", "Kuća Omišalj", 2000)
    prices = AskingPrices.from_rows(data, loc, NOW)
    x = Listing(source="t", source_id="1", url="u", title="Kuća u Njivicama", kind=HOUSE, price=300_000, area=100)
    note = prices.compare(x, "Omišalj")
    assert note.startswith("💰 25 % ispod") and "Njivice:" in note
    # Naselje bez dovoljno oglasa → cijela općina, s napomenom.
    y = Listing(source="t", source_id="2", url="u", title="Kuća Pušća", kind=HOUSE, price=300_000, area=100)
    assert "Omišalj – cijela općina" in prices.compare(y, "Omišalj")


def test_too_few_old_or_implausible_listings_ignored(loc):
    data = (rows(MIN_N - 1, "Punat", "Kuća Punat", 3000)
            + rows(5, "Punat", "Kuća Punat", 3000, last_seen="2025-01-01T10:00:00")   # starije od godinu dana
            + rows(5, "Punat", "Kuća Punat", 3000, area=10))                          # nevjerojatna površina
    prices = AskingPrices.from_rows(data, loc, NOW)
    x = Listing(source="t", source_id="1", url="u", title="Kuća Punat", kind=HOUSE, price=300_000, area=100)
    assert prices.compare(x, "Punat") is None


def test_land_only_building_land_and_labels(loc):
    data = (rows(MIN_N, "Vrbnik", "Zemljište Vrbnik", 200, kind=LAND, area=600)
            + rows(MIN_N, "Vrbnik", "Zemljište Vrbnik", 20, kind=LAND, area=600,
                   reasons='["nije građevinsko (Poljoprivredno)"]'))
    prices = AskingPrices.from_rows(data, loc, NOW)
    land = dict(source="t", source_id="1", url="u", title="Zemljište Vrbnik", kind=LAND, area=600)
    assert prices.compare(Listing(price=120_000, **land), "Vrbnik").startswith("📊 oko medijana")
    assert prices.compare(Listing(price=168_000, **land), "Vrbnik").startswith("💸 40 % iznad")
    assert prices.compare(Listing(price=48_000, **land), "Vrbnik").startswith("💰 60 % ispod")
    assert prices.compare(Listing(price=48_000, subtype="Poljoprivredno zemljište", **land), "Vrbnik") is None
    house = Listing(source="t", source_id="2", url="u", title="Kuća Vrbnik", kind=HOUSE, price=100_000, area=100)
    assert prices.compare(house, "Vrbnik") is None   # nema dovoljno oglasa kuća


def test_saved_file_and_message_line(loc, tmp_path):
    prices = AskingPrices.from_rows(rows(MIN_N, "Omišalj", "Kuća Njivice", 4000), loc, NOW)
    prices.save(tmp_path / "cijene.json")
    again = AskingPrices.from_file(tmp_path / "cijene.json", loc)
    x = Listing(source="t", source_id="1", url="u", title="Kuća Njivice", kind=HOUSE, price=300_000, area=100)
    x.extra["usporedba"] = again.compare(x, "Omišalj")
    x.extra["ppv"] = "🏛 PPV (Njivice): građevinsko 158–219 €/m² – oglas u rasponu"
    text = format_listing(x, Decision(status=WARN, jls="Omišalj"))
    assert "💰 25 % ispod medijana traženih (Njivice: 4.000 €/m²" in text
    assert text.index("🏛 PPV") < text.index("💰")   # ostvarene cijene prije traženih


def test_ppv_note(loc, tmp_path):
    from scraper.prices import Ppv

    data = {"naselja": {"Omišalj": {"njivice": {"zemljiste": [158, 219], "stanovi": {"75-100": 4200, "100+": 3200}}}},
            "gradovi_opcine": {"Omišalj": {"zemljiste": [100, 180], "stanovi": {"55-75": 3000}}}}
    (tmp_path / "ppv.json").write_text(json.dumps(data), encoding="utf-8")
    ppv = Ppv(loc, tmp_path / "ppv.json")
    land = dict(source="t", source_id="1", url="u", kind=LAND, area=600)
    assert ppv.note(Listing(title="Zemljište Njivice", price=150_000, **land), "Omišalj") == \
        "🏛 PPV (Njivice): građevinsko 158–219 €/m² – oglas 15 % iznad gornje"
    assert ppv.note(Listing(title="Zemljište Njivice", price=110_000, **land), "Omišalj").endswith("oglas u rasponu")
    assert "Omišalj – cijela općina, raspon naselja" in ppv.note(Listing(title="Zemljište", price=90_000, **land), "Omišalj")
    assert ppv.note(Listing(title="Zemljište Njivice", price=45_000, **land), "Omišalj").endswith("neobično jeftino, provjeri zašto")
    assert ppv.note(Listing(title="Poljoprivredno zemljište Njivice", price=45_000, **land), "Omišalj") is None
    house = Listing(source="t", source_id="2", url="u", title="Kuća u Njivicama", kind=HOUSE, price=300_000, area=120)
    assert ppv.note(house, "Omišalj") is None             # za kuće PPV ne postoji (stanovi su zavaravali)
