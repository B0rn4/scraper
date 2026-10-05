import pytest

from scraper.filters import evaluate
from scraper.locations import Locator
from scraper.models import HOUSE, LAND, PASS, REJECT, WARN, Listing
from scraper.runner import load_config


@pytest.fixture(scope="module")
def ctx():
    return load_config()["kriteriji"], Locator()


def house(**kw):
    base = dict(source="t", source_id="1", url="u", title="Kuća", kind=HOUSE, subtype="samostojeća kuća",
                price=300_000, area=120, county="Primorsko-goranska", municipality="Omišalj")
    base.update(kw)
    return Listing(**base)


def land(**kw):
    base = dict(source="t", source_id="2", url="u", title="Zemljište", kind=LAND, subtype="Građevinsko zemljište",
                price=150_000, area=600, county="Primorsko-goranska", municipality="Omišalj")
    base.update(kw)
    return Listing(**base)


def test_house_passes(ctx):
    assert evaluate(house(), *ctx).status == PASS


@pytest.mark.parametrize("subtype", ["dvojni objekt", "kuća u nizu", "Dvojna kuća"])
def test_semi_detached_and_terraced_rejected(ctx, subtype):
    d = evaluate(house(subtype=subtype), *ctx)
    assert d.status == REJECT


@pytest.mark.parametrize("title", ["Prodaje se etaža kuće u Puntu", "Polovica kuće, Punat", "Stan u kući, Punat"])
def test_parts_of_house_rejected(ctx, title):
    assert evaluate(house(title=title, subtype=""), *ctx).status == REJECT


def test_whole_house_with_floors_passes(ctx):
    d = evaluate(house(title="Kuća s dvije etaže i dvojnom garažom", subtype=""), *ctx)
    assert d.status == PASS


def test_price_and_area_limits(ctx):
    d = evaluate(house(price=420_000), *ctx)
    assert d.status == REJECT and d.near_miss
    d = evaluate(house(price=900_000), *ctx)
    assert d.status == REJECT and not d.near_miss
    d = evaluate(house(area=65), *ctx)
    assert d.status == REJECT and d.near_miss


def test_missing_price_or_area_warns(ctx):
    assert evaluate(house(price=None), *ctx).status == WARN
    assert evaluate(house(price=1), *ctx).status == WARN       # "cijena na upit"
    assert evaluate(house(area=None), *ctx).status == WARN


def test_location_not_on_list(ctx):
    d = evaluate(house(municipality="Novi Vinodolski"), *ctx)
    assert d.status == REJECT and "Novi Vinodolski" in d.reasons[0]
    d = evaluate(house(municipality="Bakar"), *ctx)
    assert d.status == REJECT


def test_matulji_only_the_village(ctx):
    assert evaluate(house(municipality="Matulji", settlement="Matulji"), *ctx).status == PASS
    d = evaluate(house(municipality="Matulji", settlement="Jušići"), *ctx)
    assert d.status == REJECT and "prihvaća se samo Matulji" in d.reasons[0]
    d = evaluate(house(municipality="Matulji", title="Kuća, Matulji"), *ctx)
    assert d.status == WARN and any("provjeri" in w for w in d.warnings)


def test_land_rules(ctx):
    assert evaluate(land(), *ctx).status == PASS
    assert evaluate(land(subtype="Poljoprivredno zemljište"), *ctx).status == REJECT
    assert evaluate(land(area=250), *ctx).status == REJECT
    assert evaluate(land(price=350_000), *ctx).status == REJECT


def test_land_type_from_title_when_no_subtype(ctx):
    assert evaluate(land(subtype="", title="Poljoprivredno zemljište 1400 m2"), *ctx).status == REJECT
    assert evaluate(land(subtype="", title="Građevinsko zemljište, Njivice"), *ctx).status == PASS


def test_price_per_m2_is_converted(ctx):
    d = evaluate(land(price=135, area=815), *ctx)  # 135 €/m² ≈ 110.025 €
    assert d.status == WARN and any("po m²" in w for w in d.warnings)
    d = evaluate(land(price=900, area=815), *ctx)  # ≈ 733.500 € > 300.000 €
    assert d.status == REJECT


def test_placeholder_price_means_not_given(ctx):
    d = evaluate(land(price=100, area=600), *ctx)  # "100 €" = cijena na upit
    assert d.status == WARN and "cijena nije navedena" in d.warnings


def test_fina_small_price_is_total(ctx):
    x = land(price=633.6, area=582)
    x.extra["ukupna_cijena"] = True
    d = evaluate(x, *ctx)
    assert d.status == PASS


def test_settlement_decisions():
    """Odluke iz data/naselja_udaljenosti.csv: odbijen, upozorenje s razlogom, prolaz."""
    from scraper.locations import Locator
    from scraper.models import HOUSE, Listing
    from scraper.runner import load_config

    loc, crit = Locator(), load_config()["kriteriji"]

    def house(title, municipality, settlement=""):
        return Listing(source="t", source_id="1", url="", title=title, kind=HOUSE, subtype="Samostojeća kuća",
                       price=200_000, area=120, municipality=municipality, settlement=settlement)

    d = evaluate(house("Kuća u Vrhu, pogled", "Krk"), crit, loc)
    assert d.status == "odbijen" and "Vrh: isključeno po popisu naselja (daleko od mora i od Rijeke)" in d.reasons
    d = evaluate(house("Kamena kuća", "Krk", "Brzac"), crit, loc)
    assert d.status == "upozorenje" and "Brzac: daleko od Rijeke" in d.warnings
    d = evaluate(house("Kuća Glavani", "Kostrena"), crit, loc)
    assert "Glavani: daleko od mora" in d.warnings
    assert "Zamet: grad Rijeka" in evaluate(house("Kuća Zamet", "Rijeka"), crit, loc).warnings
    assert "grad Rijeka" in evaluate(house("Kuća", "Rijeka"), crit, loc).warnings
    assert evaluate(house("Kuća Omišalj", "Omišalj", "Njivice"), crit, loc).status == "prolazi"
    # Samo grad/općina: prolazi; napomena samo kad je imaju sva prihvaćena naselja.
    assert evaluate(house("Kuća", "Dobrinj"), crit, loc).status == "prolazi"
    assert "Krk: daleko od Rijeke" in evaluate(house("Kuća", "Krk"), crit, loc).warnings
    # Drugi naziv s karte (Poljice = Poljica); mjesto iz odbijene općine.
    assert "Poljica: daleko od mora i od Rijeke" in evaluate(house("Kuća Poljice", "Krk"), crit, loc).warnings
    assert evaluate(house("Kuća Klenovica", "Novi Vinodolski"), crit, loc).status == "odbijen"


def test_risky_phrases():
    from scraper.locations import Locator
    from scraper.models import HOUSE, Listing
    from scraper.runner import load_config

    loc, crit = Locator(), load_config()["kriteriji"]

    def house(desc):
        return Listing(source="t", source_id="1", url="", title="Kuća Omišalj", kind=HOUSE, subtype="Samostojeća kuća",
                       price=250_000, area=120, municipality="Omišalj", description=desc)

    share = evaluate(house("Prodajem svoj suvlasnički dio kuće. Lijep pogled."), crit, loc)
    assert share.status == "odbijen" and "suvlasnički dio" in share.reasons[0]
    heirs = evaluate(house("Kuća je u vlasništvu više nasljednika, svi su suglasni."), crit, loc)
    assert heirs.status == "upozorenje" and any("nasljednici" in w and "„" in w for w in heirs.warnings)
    clean = evaluate(house("Vlasništvo 1/1, bez tereta. Legalizirano. Kolni pristup i parking."), crit, loc)
    assert clean.status == "prolazi"
