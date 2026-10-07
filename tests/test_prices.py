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


CRITERIA = {HOUSE: {"max_cijena": 400_000, "min_povrsina": 70}, LAND: {"max_cijena": 300_000, "min_povrsina": 300}}


def area_rows(n, ppm, area, kind=HOUSE, status="prolazi", **kw):
    return [dict(r, status=status) for r in rows(n, "Omišalj", "Kuća Njivice", ppm, kind=kind, area=area, **kw)]


def test_area_average_by_size_band_only_listings_within_criteria(loc):
    from scraper.prices import AREA_MIN_N

    data = (area_rows(AREA_MIN_N, 2500, 110)                         # razred 100–129 m²
            + area_rows(AREA_MIN_N, 9000, 115, status="odbijen")     # odbijeni ne ulaze
            + area_rows(AREA_MIN_N, 5000, 120, status="upozorenje")  # skuplji od granice (parcelacija i sl.) ne ulaze
            + area_rows(AREA_MIN_N, 1000, 300)                       # drugi razred
            + area_rows(AREA_MIN_N - 1, 3000, 80))                   # premalo oglasa u razredu
    data.append(dict(data[0], price=110 * 15_000))                   # pogrešno upisana: izvan granice cijene
    prices = AskingPrices.from_rows(data, loc, NOW, CRITERIA)
    assert prices.area[f"{HOUSE}|100"]["n"] == AREA_MIN_N
    assert prices.area[f"{HOUSE}|100"]["prosjek"] == 2500
    assert prices.area[f"{HOUSE}|250"]["prosjek"] == 1000
    assert f"{HOUSE}|70" not in prices.area
    x = Listing(source="t", source_id="1", url="u", title="Kuća", kind=HOUSE, price=242_000, area=110)
    assert prices.area_note(x) == ("📐 Prosjek područja, kuće 100–129 m² (10 oglasa): 2.500 €/m² – ovaj 12 % ispod")
    assert prices.area_short(x) == "područje −12 %"
    big = Listing(source="t", source_id="2", url="u", title="Kuća", kind=HOUSE, price=310_000, area=300)
    assert prices.area_note(big).startswith("📐 Prosjek područja, kuće od 250 m² (10 oglasa): 1.000 €/m² – ovaj 3 % iznad")
    same = Listing(source="t", source_id="3", url="u", title="Kuća", kind=HOUSE, price=301_000, area=300)
    assert prices.area_note(same).endswith("ovaj ≈ prosjek") and prices.area_short(same) == "područje ≈ prosjek"
    small = Listing(source="t", source_id="4", url="u", title="Kuća", kind=HOUSE, price=240_000, area=80)
    assert prices.area_note(small) is None


def test_area_average_land_saved_for_redmi(loc, tmp_path):
    data = (area_rows(12, 200, 600, kind=LAND)
            + area_rows(12, 20, 600, kind=LAND, reasons='["nije građevinsko (Poljoprivredno)"]'))
    prices = AskingPrices.from_rows(data, loc, NOW, CRITERIA)
    prices.save(tmp_path / "cijene.json")
    again = AskingPrices.from_file(tmp_path / "cijene.json", loc)
    land = Listing(source="t", source_id="1", url="u", title="Zemljište", kind=LAND, price=150_000, area=600)
    assert again.area_note(land) == "📐 Prosjek područja, zemljišta 300–799 m² (12 oglasa): 200 €/m² – ovaj 25 % iznad"
    farm = Listing(source="t", source_id="2", url="u", title="Poljoprivredno zemljište", kind=LAND, price=15_000,
                   area=600)
    assert again.area_note(farm) is None
    # Stara datoteka (Redmi prije ove promjene) nema prosjek područja.
    (tmp_path / "stara.json").write_text(json.dumps({"izracunato": "", "grupe": {}}), encoding="utf-8")
    assert AskingPrices.from_file(tmp_path / "stara.json", loc).area_note(land) is None


def test_area_line_in_message_after_ppv(loc):
    x = Listing(source="t", source_id="1", url="u", title="Zemljište Njivice", kind=LAND, price=150_000, area=600)
    x.extra["ppv"] = "🏛 PPV (Njivice): građevinsko 158–219 €/m² – oglas 15 % iznad gornje"
    x.extra["prosjek"] = "📐 Prosjek područja, zemljišta 300–799 m² (12 oglasa): 200 €/m² – ovaj 25 % iznad"
    x.extra["usporedba"] = "💸 25 % iznad medijana traženih (Njivice: 200 €/m², 40 oglasa)"
    text = format_listing(x, Decision(status=WARN, jls="Omišalj"))
    assert text.index("🏛 PPV") < text.index("📐") < text.index("💸")
