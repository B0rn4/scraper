import pytest

from scraper.locations import Locator


@pytest.fixture(scope="module")
def loc():
    return Locator()


def names(loc, text):
    return {j.name for j, _ in loc.scan_text(text)}


def with_inclusion(loc, text):
    return {(j.name, j.included) for j, _ in loc.scan_text(text)}


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Prodaja zemljišta u Puntu", "Punat"),
        ("obiteljska kuća u Omišlju", "Omišalj"),
        ("kuća u Novom Vinodolskom", "Novi Vinodolski"),
        ("stan u Rijeci", "Rijeka"),
        ("kuća na otoku Krku", "Krk"),
        ("u Mošćenicama", "Mošćenička Draga"),
        ("u Mošćeničkoj Dragi", "Mošćenička Draga"),
        ("Staroj Baški", "Punat"),
        ("Ičićima", "Opatija"),
        ("u Selcu", "Crikvenica"),
        ("Kostrena Sv. Lucija", "Kostrena"),
        ("Bakarac", "Kraljevica"),
        ("Punta Kolova", "Opatija"),
    ],
)
def test_places_in_all_cases(loc, text, expected):
    assert expected in names(loc, text)


@pytest.mark.parametrize(
    "text",
    [
        "Kuća u Baškoj Vodi",          # Makarska, ne Baška
        "Stan u Mošćenici kod Petrinje",  # selo kod Petrinje, ne Mošćenice
        "slapovi Krke, NP Krka",        # rijeka Krka
        "prezime Bakarić",
        "riječ je o kući",
        "kraj mora, polje i vrh brda",  # obične riječi
    ],
)
def test_false_positives_are_ignored(loc, text):
    assert not any(inc for _, inc in with_inclusion(loc, text))


def test_excluded_places(loc):
    assert ("Bakar", False) in with_inclusion(loc, "nekretnina u Bakru")
    assert ("Rab", False) in with_inclusion(loc, "Supetarska Draga na Rabu")
    assert ("Novi Vinodolski", False) in with_inclusion(loc, "kuća u Novom Vinodolskom")
    assert ("Mošćenička Draga", False) in with_inclusion(loc, "u Mošćeničkoj Dragi")


def test_structured_fields(loc):
    assert loc.by_name("Malinska").name == "Malinska-Dubašnica"
    assert loc.by_name("Opatija - Okolica").name == "Opatija"
    assert loc.by_name("Grad Krk").name == "Krk"
    assert not loc.by_name("Bakar").included
    r = loc.resolve(settlement="Mučići", county="Primorsko-goranska")
    assert r.jls.name == "Matulji"
    assert loc.resolve(municipality="Umag", county="Istarska").included is False


def test_name_in_two_places_is_ambiguous(loc):
    r = loc.resolve(text="Martinšćica")  # Kostrena i Cres
    assert r.ambiguous and r.included is True


def test_same_settlement_name_resolved_by_text():
    """Susak (otok, Mali Lošinj) i Sušak (Rijeka) bez dijakritika su isti naziv: odlučuje tekst."""
    loc = Locator()
    r = loc.resolve(settlement="Susak", text="Susak (Mali Lošinj) Mali Lošinj, otok Susak - starina")
    assert r.jls.name == "Mali Lošinj" and r.included is False
    assert loc.resolve(settlement="Sušak", text="Rijeka, Sušak, kuća").included is True
    assert loc.resolve(settlement="Susak", text="SUSAK, kuća u najmu").jls is None      # bez drugog traga: ⚠
