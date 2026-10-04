"""Logika obavijesti (nov oglas, snižena cijena, početni popis) bez mreže."""

from scraper import report
from scraper.db import State
from scraper.models import HOUSE, PASS, REJECT, Decision, Listing
from scraper.runner import Runner


def listing(price=300_000, sid="1"):
    return Listing(source="t", source_id=sid, url="https://x", title="Kuća Punat", kind=HOUSE,
                   subtype="samostojeća kuća", price=price, area=120, county="Primorsko-goranska", municipality="Punat")


def test_notify_reasons(tmp_path):
    runner = Runner(tmp_path / "s.db", tmp_path, send=False)
    state = State(tmp_path / "s.db")
    ok = Decision(PASS, jls="Punat")

    # Nov oglas koji prolazi → obavijest.
    assert runner._notify_reason(listing(), ok, None) == ""
    # Već poslan, bez promjene → ništa.
    state.upsert(listing(), ok, "t1")
    state.mark_notified("t:1", 300_000, "t1")
    assert runner._notify_reason(listing(), ok, state.get("t:1")) is None
    # Snižena cijena već poslanog → obavijest o sniženju.
    assert runner._notify_reason(listing(280_000), ok, state.get("t:1")).startswith("📉 Snižena cijena")
    # Prije odbijen zbog cijene, sad prolazi → obavijest.
    state.upsert(listing(450_000, "2"), Decision(REJECT, ["cijena"]), "t1")
    assert "sad odgovara" in runner._notify_reason(listing(390_000, "2"), ok, state.get("t:2"))
    # Odbijen oglas → nikad obavijest.
    assert runner._notify_reason(listing(), Decision(REJECT, ["x"]), None) is None
    state.close()


def test_report_html(tmp_path):
    entries = [report.entry(listing(), Decision(PASS, jls="Punat")),
               report.entry(listing(450_000, "2"), Decision(REJECT, ["cijena 450.000 € > 400.000 €"], near_miss=True))]
    path = report.write(tmp_path / "r.html", entries, "Pregled", "danas", [{"label": "test", "total": 2, "links": []}])
    text = path.read_text()
    assert "Kopiraj označene" in text and "Kuća Punat" in text and "za dlaku" in text
    assert entries[1]["cat"] == ["cijena"]
