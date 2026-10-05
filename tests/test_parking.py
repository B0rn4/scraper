from scraper.filters import evaluate
from scraper.locations import Locator
from scraper.models import HOUSE, LAND, PASS, WARN, Decision, Listing
from scraper.notify import format_listing, summary_line
from scraper.parking import check, plot_from_text
from scraper.runner import load_config

LONG = " Kuća ima tri sobe, kuhinju, dnevni boravak i lijepu terasu s pogledom na more i otoke."


def house(desc="", **kw):
    base = dict(source="t", source_id="1", url="u", title="Kuća", kind=HOUSE, subtype="Samostojeća kuća",
                price=250_000, area=120, municipality="Omišalj", description=desc)
    base.update(kw)
    return Listing(**base)


def test_parking_from_text_and_fields():
    assert check(house("Uz kuću je garaža." + LONG)) == ("🚗 garaža (iz opisa)", "")
    assert check(house("Posjeduje vlastiti parking, a gradski parking je 20 m dalje." + LONG))[0] == "🚗 parking (iz opisa)"
    assert check(house(extra={"parking": "vanjsko parkirno mjesto"}))[0] == "🚗 vanjsko parkirno mjesto"
    assert check(house(extra={"parking": "2"}))[0] == "🚗 parkirnih mjesta: 2"
    line, warning = check(house("Kuća nema vlastito parkirno mjesto, parkiranje je na javnoj površini." + LONG))
    assert not line and warning.startswith("parking: „Kuća nema vlastito parkirno mjesto")
    assert check(house("Javni parking je u blizini." + LONG))[1] == "parking: „Javni parking je u blizini.”"
    assert check(Listing(source="t", source_id="2", url="u", title="Zemljište", kind=LAND)) == ("", "")


def test_parking_plot_and_missing():
    assert plot_from_text("Kuća s okućnicom od 350 m2, mirno.") == 350
    assert check(house(LONG, plot_area=200)) == ("🚗 parking nije naveden – okućnica 200 m²", "")
    assert check(house("Okućnica površine 350 m2 je ograđena." + LONG))[0] == "🚗 parking nije naveden – okućnica 350 m²"
    assert check(house(LONG)) == ("", "parking nije naveden – provjeri")
    assert check(house(LONG, plot_area=40)) == ("", "parking nije naveden (okućnica 40 m²) – provjeri")
    assert check(house("Kratko."))[0] == "🚗 parking: nema podataka (oglas bez opisa)"
    assert check(house(LONG, extra={"opis_skracen": True}))[1] == ""          # skraćeni opis s popisa


def test_parking_in_evaluate_and_message():
    crit, loc = load_config()["kriteriji"], Locator()
    d = evaluate(house(LONG, settlement="Njivice"), crit, loc)
    assert d.status == WARN and "parking nije naveden – provjeri" in d.warnings
    x = house("Kuća s garažom." + LONG, settlement="Njivice")
    d = evaluate(x, crit, loc)
    assert d.status == PASS and "🚗 garaža (iz opisa)" in format_listing(x, d)


def test_summary_line():
    crit, loc = load_config()["kriteriji"], Locator()
    x = house("Kuća s garažom." + LONG, title="Kuća Bogovići", municipality="Malinska-Dubašnica")
    d = evaluate(x, crit, loc)
    x.extra["cijena_kratko"] = ["cijena −20 % od prosjeka"]
    assert summary_line(x, d) == "📊 more 0,6 km · Rijeka 40 min · Zagreb 2 h 24 min · cijena −20 % od prosjeka · ⚠ 1"
    assert "📍 Malinska-Dubašnica – Bogovići" in format_listing(x, d)
    y = house("Kuća s garažom." + LONG, title="Kuća", municipality="Krk")     # samo grad: mjere za mjesto Krk
    d = evaluate(y, crit, loc)
    assert summary_line(y, d).startswith("📊 ~Krk: more 0,2 km · Rijeka 53 min")
    assert summary_line(house(), Decision(PASS)) == ""
