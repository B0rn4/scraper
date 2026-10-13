"""Priključci zemljišta (redak 🔌, odluka korisnika 13. 10.)."""

from scraper import prikljucci
from scraper.models import HOUSE, LAND, Listing


def land(description="", **extra):
    return Listing("t", "1", "u", "Građevinsko zemljište", LAND, description=description, extra=dict(extra))


def test_labels_from_portals():
    """Nazivi polja s portala (hrvatski, talijanski s nekretnine.hr), redom struja, voda, …;
    "Struja: Ne" i grijanje nisu priključak."""
    assert prikljucci.from_labels(["Priključak za vodu", "Kanalizacijski priključak", "Plinski priključak",
                                   "allaccio elettricità", "illuminazione pubblica", "Asfaltni put", "Septička"]) == [
        "struja", "voda", "kanalizacija", "septička jama", "plin", "asfaltni put", "javna rasvjeta"]
    assert prikljucci.from_labels(["Gradski vodovod", "Struja: Ne", "Električno grijanje", "Klima uređaj: Da"]) == ["voda"]
    assert prikljucci.merge(["voda"], ["struja", "voda"]) == ["struja", "voda"]


def test_line_from_fields_description_or_nothing():
    assert prikljucci.check(land(prikljucci=["struja", "voda"])) == "🔌 priključci: struja ✔ · voda ✔"
    assert prikljucci.check(land("Ravan teren. Struja i voda su uz parcelu. Pogled na more.")) == \
        "🔌 priključci (iz opisa): „Struja i voda su uz parcelu.”"
    # Rečenica o priključcima općenito ima prednost; i "nema" se citira (opis zna reći i to).
    assert prikljucci.check(land("Voda na 50 m. Sva infrastruktura je uz parcelu.")) == \
        "🔌 priključci (iz opisa): „Sva infrastruktura je uz parcelu.”"
    assert prikljucci.check(land("Iako nema provedene infrastrukture, cijena je povoljna.")).startswith("🔌 priključci (iz opisa): „Iako nema")
    # Pogled na more i vodu, čvor brze ceste, društvena infrastruktura – nisu priključci.
    for text in ("Parcela s pogledom na more i vodu.", "Priključak na brzu cestu je na 2 km.",
                 "Društvena infrastruktura: škola i bolnica u blizini."):
        assert prikljucci.check(land(text)) == "🔌 priključci nisu navedeni", text
    assert prikljucci.check(land("Prilaz asfaltiranom cestom do parcele.")) == \
        "🔌 priključci nisu navedeni · pristup (iz opisa): „Prilaz asfaltiranom cestom do parcele.”"
    # Skraćen opis s popisa: ne zna se (bez retka); pristup s nekretnine.hr ide uz redak.
    assert prikljucci.check(land("Kratko.", opis_skracen=True)) == ""
    assert prikljucci.check(land(prikljucci=["voda"], pristup="Na makadamskoj cesti")) == \
        "🔌 priključci: voda ✔ · pristup: na makadamskoj cesti"
    assert prikljucci.check(Listing("t", "1", "u", "Kuća", HOUSE, description="Struja i voda.")) == ""


def test_long_sentence_is_quoted_around_the_mention():
    """Nabrajanje u jednoj rečenici: citat počinje kod priključaka, interpunkcija ostaje."""
    text = ("1/1, uredno, bez tereta, pristupni put, struja, voda 50 m, zemljište je u koridoru nove "
            "željezničke pruge, cijena 35 €/m2, vlasnički list na uvid ozbiljnim kupcima, bez agencije i provizije.")
    line = prikljucci.check(land(text))
    assert line.startswith("🔌 priključci (iz opisa): „…struja, voda 50 m") and line.endswith("…”")
    assert len(line) < 190
