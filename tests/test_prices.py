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


def test_market_share_by_size_band_only_listings_within_criteria(loc):
    data = (area_rows(10, 2500, 110)                         # razred 100–129 m²: 2.410 … 2.590 €/m²
            + area_rows(10, 9000, 115, status="odbijen")     # odbijeni ne ulaze
            + area_rows(10, 5000, 120, status="upozorenje")  # skuplji od granice (parcelacija i sl.) ne ulaze
            + area_rows(10, 1000, 300)                       # drugi razred
            + area_rows(9, 3000, 80))                        # premalo oglasa u razredu
    data.append(dict(data[0], price=110 * 15_000))           # pogrešno upisana: izvan granice cijene
    prices = AskingPrices.from_rows(data, loc, NOW, CRITERIA)
    x = Listing(source="t", source_id="1", url="u", title="Kuća Njivice", kind=HOUSE, price=242_000, area=110)
    area, place, short = prices.describe(x, "Omišalj")
    assert area == "📐 Područje, kuće 100–129 m² (10): medijan 2.500 €/m² – ovaj 12 % ispod · skuplji od 0 %"
    # Svih 10 je u Njivicama: naselje ima dovoljno oglasa.
    assert place == "🏘 Njivice, kuće 100–129 m² (10): medijan 2.500 €/m² – ovaj 12 % ispod · skuplji od 0 %"
    assert short == "skuplji od 0 % područja, 0 % mjesta"
    mid = Listing(source="t", source_id="2", url="u", title="Kuća Njivice", kind=HOUSE, price=275_000, area=110)
    assert prices.market_short(mid, "Omišalj") == "skuplji od 50 % područja, 50 % mjesta"
    top = Listing(source="t", source_id="3", url="u", title="Kuća", kind=HOUSE, price=300_000, area=110)
    assert prices.market_notes(top, "Omišalj")[0].endswith("ovaj 9 % iznad · skuplji od 100 %")
    # Bez naselja u oglasu: cijela općina.
    assert prices.market_notes(top, "Omišalj")[1].startswith("🏘 Omišalj – cijela općina, kuće 100–129 m² (10)")
    small = Listing(source="t", source_id="4", url="u", title="Kuća", kind=HOUSE, price=240_000, area=80)
    assert [n[:2] for n in prices.market_notes(small, "Omišalj")] == ["🏘 "]  # područje: premalo (9 − sam oglas)
    # Isti oglas (ključ) i njegova kopija na drugom portalu (ista cijena i površina) ne broje se.
    first = data[0]
    same = Listing(source="t", source_id="x", url="u", title="Kuća", kind=HOUSE, price=first["price"], area=110)
    assert "(9)" in prices.market_notes(same, "Omišalj")[0]


def test_market_renovation_compared_separately(loc):
    data = area_rows(10, 2500, 110) + [dict(r, category="obnova") for r in area_rows(10, 900, 150)]
    prices = AskingPrices.from_rows(data, loc, NOW, CRITERIA)
    ruin = Listing(source="t", source_id="1", url="u", title="Stara kamena kuća za obnovu", kind=HOUSE,
                   price=100_000, area=100)
    assert prices.market_notes(ruin, "Omišalj")[0].startswith(
        "📐 Područje, kuće za obnovu ili nedovršene (10): medijan 900 €/m² – ovaj 11 % iznad · skuplji od 100 %")
    ready = Listing(source="t", source_id="2", url="u", title="Kuća", kind=HOUSE, price=200_000, area=110)
    assert "(10): medijan 2.500" in prices.market_notes(ready, "Omišalj")[0]
    # Kategorija iz opisa (spremljena u bazi) vrijedi i kad naslov ništa ne kaže.
    hidden = Listing(source="t", source_id="3", url="u", title="Kuća", kind=HOUSE, price=100_000, area=100,
                     extra={"kategorija": "obnova"})
    assert "za obnovu" in prices.market_notes(hidden, "Omišalj")[0]
    # Premalo kuća za obnovu: bez usporedbe (medijan svih kuća bi rekao "neobično jeftino").
    few = AskingPrices.from_rows(area_rows(10, 2500, 110), loc, NOW, CRITERIA)
    few.groups = {f"{HOUSE}|Omišalj|": {"n": 50, "med": 2500}}
    assert few.describe(ruin, "Omišalj") == (None, None, None)
    assert few.describe(Listing(source="t", source_id="4", url="u", title="Kuća", kind=HOUSE, price=200_000,
                                area=300), "Omišalj")[1].startswith("💰")    # 250+ m²: nema po kriterijima


def test_market_saved_for_redmi(loc, tmp_path):
    data = (area_rows(12, 200, 600, kind=LAND)
            + area_rows(12, 20, 600, kind=LAND, reasons='["nije građevinsko (Poljoprivredno)"]'))
    prices = AskingPrices.from_rows(data, loc, NOW, CRITERIA)
    prices.save(tmp_path / "cijene.json")
    again = AskingPrices.from_file(tmp_path / "cijene.json", loc)
    land = Listing(source="t", source_id="1", url="u", title="Zemljište", kind=LAND, price=150_000, area=600)
    assert again.market_notes(land, "Omišalj")[0].startswith(
        "📐 Područje, zemljišta 300–799 m² (12): medijan 200 €/m² – ovaj 25 % iznad · skuplji od 100 %")
    farm = Listing(source="t", source_id="2", url="u", title="Poljoprivredno zemljište", kind=LAND, price=15_000,
                   area=600)
    assert again.market_notes(farm, "Omišalj") == []
    # Stara datoteka (Redmi prije ove promjene): bez usporedbe po kriterijima.
    (tmp_path / "stara.json").write_text(json.dumps({"izracunato": "", "grupe": {}}), encoding="utf-8")
    assert AskingPrices.from_file(tmp_path / "stara.json", loc).market_notes(land, "Omišalj") == []


def test_share_below_counts_ties_half():
    from scraper.prices import share_below
    assert share_below([1, 2, 4, 5], 3) == 50 and share_below([1, 2, 3, 4], 3) == 62 and share_below([1, 2, 3, 4], 5) == 100 and share_below([5], 1) == 0


def test_area_line_in_message_after_ppv(loc):
    x = Listing(source="t", source_id="1", url="u", title="Zemljište Njivice", kind=LAND, price=150_000, area=600)
    x.extra["ppv"] = "🏛 PPV (Njivice): građevinsko 158–219 €/m² – oglas 15 % iznad gornje"
    x.extra["prosjek"] = "📐 Prosjek područja, zemljišta 300–799 m² (12 oglasa): 200 €/m² – ovaj 25 % iznad"
    x.extra["usporedba"] = "💸 25 % iznad medijana traženih (Njivice: 200 €/m², 40 oglasa)"
    text = format_listing(x, Decision(status=WARN, jls="Omišalj"))
    assert text.index("🏛 PPV") < text.index("📐") < text.index("💸")
