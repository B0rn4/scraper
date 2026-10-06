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
    # Odluka po nazivu naselja i kad ga portal vodi pod drugom općinom (Oprič je u popisu pod Opatijom).
    assert evaluate(house("Kuća", "Lovran", "Oprič"), crit, loc).status == "odbijen"
    assert evaluate(house("Kuća Oprič", "Lovran"), crit, loc).status == "odbijen"
    assert evaluate(house("Kuća Lovran", "Lovran"), crit, loc).status == "prolazi"


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


def test_place_outside_county_rejected(ctx):
    """burza.com.hr (Kvarner i Istra): naselje izvan PGŽ-a odbija oglas i kad naslov spominje naše mjesto."""
    def burza(settlement, title):
        x = house(county="", municipality="", settlement=settlement, location_text=settlement, title=title,
                  description="Samostojeća kuća s parkingom.")
        x.extra["samo_pgz"] = True
        return evaluate(x, *ctx)

    d = burza("Karlobag", "Barić Draga, prvi red do mora")
    assert d.status == REJECT and "izvan PGŽ-a: Karlobag" in d.reasons[0]
    assert burza("Galižana", "Istarska kamena kuća").status == REJECT
    assert burza("Dramalj", "Dramalj – uređena primorska kuća").status != REJECT
    assert burza("Rijeka, Donja Drenova", "Samostojeća kuća").jls == "Rijeka"


def test_heritage_phrases(ctx):
    def w(desc):
        return [x for x in evaluate(house(description=desc), *ctx).warnings if x.startswith("kulturno dobro")]

    assert w("Kamena kuća u zaštićenoj staroj gradskoj jezgri, uz suglasnost konzervatora.")
    assert w("Kuća je upisana u Registar kulturnih dobara RH.")
    assert w("Nalazi se unutar kulturno-povijesne cjeline grada Kastva.")
    assert not w("Kuća nije pod zaštitom konzervatora.")
    assert not w("Novogradnja s pogledom na more, 5 minuta od plaže.")


def test_price_on_request_luxury(ctx):
    """"Cijena na upit": luksuzna (riječi + procjena) ili golema kuća se odbija, ostale ⚠ s procjenom."""
    from scraper.prices import AskingPrices

    prices = AskingPrices(ctx[1], {"kuca|Omišalj|": {"n": 50, "med": 3500}, "zemljiste|Omišalj|": {"n": 30, "med": 250}})

    def d(price=1, **kw):
        return evaluate(house(price=price, description="Kuća s parkingom.", **kw), *ctx, prices)

    vila = d(title="Luksuzna vila s bazenom", area=300)              # 300 × 3.500 × 0,4 = 420.000 > 400.000
    assert vila.status == REJECT and vila.reasons[0].startswith("cijena na upit – luksuzna, procjena ≈ 1.050.000 €")
    assert d(title="Obiteljska kuća", area=700).status == REJECT      # 700 × 3.500 × 0,2 = 490.000
    obicna = d(title="Obiteljska vila", area=110)                      # riječ "vila", ali procjena 385.000
    assert obicna.status == WARN and "cijena na upit – procjena ≈ 385.000 € (medijan traženih Omišalj" in " ".join(obicna.warnings)
    assert "cijena nije navedena" in evaluate(house(price=1, description="Kuća s parkingom."), *ctx).warnings  # bez medijana
    teren = dict(price=100, title="Građevinsko zemljište s panoramskim pogledom")
    assert evaluate(land(area=4000, **teren), *ctx, prices).status == REJECT     # 4.000 × 250 × 0,4 = 400.000 > 300.000
    assert evaluate(land(area=2000, **teren), *ctx, prices).status == WARN       # 200.000: može biti u granici
    assert evaluate(land(area=9000, price=100, title="Građevinsko zemljište"), *ctx, prices).status == WARN  # bez riječi


def test_price_on_request_unfinished_kept(ctx):
    """Starina ili Rohbau "na upit" ne odbija se ni kad je velika (cijena po m² je niska)."""
    from scraper.prices import AskingPrices

    prices = AskingPrices(ctx[1], {"kuca|Omišalj|": {"n": 50, "med": 3500}})
    for title in ("OTOK KRK - Rohbau s bazenom i pogledom na more", "Starina u blizini grada Krka",
                  "Kuća, započeta gradnja 450m2 s panoramskim pogledom"):
        d = evaluate(house(price=1, area=660, title=title, description="Parking."), *ctx, prices)
        assert d.status == WARN, title
    vila = evaluate(house(price=1, area=349, title="Luksuzna vila u izgradnji", description="Parking."), *ctx, prices)
    assert vila.status == REJECT                                       # "u izgradnji" ne spašava luksuznu


def test_numbers_and_areas_in_text():
    """Svježi pregled koda: "0,345" je decimalni broj, a razmak razdvaja tisuće ("1 200 m2")."""
    from scraper.text import areas_in_text, parse_number

    assert (parse_number("0,345"), parse_number("1,200"), parse_number("1.234,5")) == (0.345, 1200, 1234.5)
    assert areas_in_text("teren 1 200 m2") == [1200.0]
    assert areas_in_text("0,345 ha") == [3450.0]
    assert areas_in_text("kuća 150 m2, okućnica 1.200 m2, 3 sobe") == [150.0, 1200.0]


def test_ideal_part_of_town_is_not_a_share(ctx):
    """"U idealnom dijelu Malinske" je opis mjesta, ne prodaja idealnog (suvlasničkog) dijela."""
    for text in ("Prodajemo kuću u idealnom dijelu Malinske.", "Nudimo kuću na idealnom dijelu otoka Krka."):
        assert evaluate(house(description=text), *ctx).status != REJECT
    for text in ("Prodaje se idealni dio od 1/2 kuće.", "Prodajem 1/2 idealnog dijela kuće.",
                 "Idealni dio nekretnine se prodaje."):
        assert evaluate(house(description=text), *ctx).status == REJECT


def test_zero_area_means_not_given(ctx):
    d = evaluate(land(area=0), *ctx)
    assert d.status == WARN and "površina nije navedena" in d.warnings


def test_third_review_land_rules(ctx):
    """Negrađevinsko nije građevinsko; zemljište 10–99 €/m² je stvarna cijena po m²
    (100 € je zamjena za "na upit"); "polovica kuće je renovirana" nije prodaja dijela."""
    d = evaluate(land(subtype="", title="Negrađevinsko zemljište, Omišalj"), *ctx)
    assert d.status == REJECT and "nije građevinsko" in d.reasons[0]
    assert evaluate(land(subtype="Poljoprivredno", title="Negrađevinsko zemljište 1370m2"), *ctx).status == REJECT
    d = evaluate(land(price=55, area=2442), *ctx)
    assert d.status == WARN and any("ukupno ≈ 134.310 €" in w for w in d.warnings)
    assert "cijena nije navedena" in evaluate(land(price=100, area=600), *ctx).warnings
    assert "cijena nije navedena" in evaluate(land(price=5, area=600), *ctx).warnings
    assert "cijena nije navedena" in evaluate(house(price=55), *ctx).warnings
    assert evaluate(house(description="Prodajem kuću, polovica kuće je renovirana 2020."), *ctx).status != REJECT
    assert evaluate(house(description="Prodajem 1/2 kuće."), *ctx).status == REJECT


def test_fourth_review_rules(ctx):
    """"Soline, građevinsko" i "Atraktivan građevinski teren" jesu građevinsko; kuća za 3.000 €
    uz 180 m² je cijena po m²; suvlasnički dio zajedničkog puta/dvorišta nije prodaja dijela."""
    for title in ("Soline, građevinsko zemljište 800 m2", "Atraktivan građevinski teren", "Opatija, Poljane - građevinsko"):
        d = evaluate(land(subtype="", title=title), *ctx)
        assert "vrsta zemljišta nije navedena" not in d.warnings and not any("nije građevinsko" in r for r in d.reasons), title
    d = evaluate(house(price=3_000, area=180), *ctx)
    assert d.status == REJECT and "cijena 540.000 € > 400.000 €" in d.reasons
    assert "cijena" not in " ".join(evaluate(house(price=9_000, area=80), *ctx).warnings)   # 112 €/m²: ukupna
    for text in ("Prodajem kuću i suvlasnički dio zajedničkog dvorišta.", "Prodaje se kuća te idealni dio od 1/3 zajedničkog puta."):
        assert evaluate(house(description=text), *ctx).status != REJECT, text
    assert evaluate(house(description="Prodaje se suvlasnički dio kuće (1/2)."), *ctx).status == REJECT


def test_burza_place_must_be_whole_name():
    loc = Locator()
    for place in ("Barić Draga", "Kraj Drage", "Sveti Ivan, Općina Oprtalj"):
        assert not loc.knows(place), place
    for place in ("Rijeka, Donja Drenova", "Kostrena Sveta Lucija", "Grižane-Belgrad", "Opatija - Volosko", "Malinska"):
        assert loc.knows(place), place
