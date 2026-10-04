import pytest

from scraper.locations import Locator


@pytest.fixture(scope="module")
def loc():
    return Locator()


def names(loc, text):
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
def test_included_places_in_all_cases(loc, text, expected):
    assert (expected, True) in names(loc, text)


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
    assert not any(inc for _, inc in names(loc, text))


def test_excluded_places(loc):
    assert ("Bakar", False) in names(loc, "nekretnina u Bakru")
    assert ("Rab", False) in names(loc, "Supetarska Draga na Rabu")


def test_structured_fields(loc):
    assert loc.by_name("Malinska").name == "Malinska-Dubašnica"
    assert loc.by_name("Opatija - Okolica").name == "Opatija"
    assert loc.by_name("Grad Krk").name == "Krk"
    assert not loc.by_name("Matulji").included
    r = loc.resolve(settlement="Mučići", county="Primorsko-goranska")
    assert r.jls.name == "Matulji" and r.included is False
    assert loc.resolve(municipality="Umag", county="Istarska").included is False


def test_name_in_two_places_is_ambiguous(loc):
    r = loc.resolve(text="Martinšćica")  # Kostrena i Cres
    assert r.ambiguous and r.included is True
