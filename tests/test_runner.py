"""Logika obavijesti (nov oglas, snižena cijena, početni popis) bez mreže."""

from scraper import report
from scraper.db import State
from scraper.models import HOUSE, PASS, REJECT, Decision, Listing
from scraper.runner import Runner


def listing(price=300_000, sid="1", area=120, title="Kuća Punat", source="t"):
    return Listing(source=source, source_id=sid, url="https://x", title=title, kind=HOUSE,
                   subtype="samostojeća kuća", price=price, area=area, county="Primorsko-goranska", municipality="Punat")


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


class FakeSource:
    name, label, daily = "fake", "fake", False
    batches = []

    def __init__(self, *a, **k):
        pass

    def fetch(self, mode, known_ids):
        FakeSource.modes.append(mode)
        return FakeSource.batches.pop(0)

    def search_links(self):
        return []


def test_baseline_then_incremental(tmp_path, monkeypatch):
    import scraper.runner as runner_mod

    monkeypatch.setitem(runner_mod.ALL, "fake", FakeSource)
    FakeSource.modes = []
    FakeSource.batches = [[listing(sid="1"), listing(900_000, "2")],          # početni popis
                          [listing(sid="1"), listing(sid="3", area=95), listing(380_000, "2")]]  # novi + snižen
    sent = []

    def run_once():
        r = Runner(tmp_path / "s.db", tmp_path / "out", send=False)
        r.cfg["izvori"] = {"fake": True}
        r._send_report = lambda *a, **k: sent.append(("report", a[1]))
        r._send_notifications = lambda state, items: sent.extend(("msg", x.source_id, h) for x, d, h in items)
        r.run(force=True)

    run_once()
    assert FakeSource.modes == ["full"] and [s[0] for s in sent] == ["report"]
    sent.clear()
    run_once()
    assert FakeSource.modes == ["full", "incremental"]
    msgs = {s[1]: s[2] for s in sent}
    assert set(msgs) == {"2", "3"} and "📉" in msgs["2"] and msgs["3"] == ""


def test_weekly_excludes_baseline(tmp_path):
    state = State(tmp_path / "s.db")
    near = Decision(REJECT, ["cijena 420.000 € > 400.000 €"], near_miss=True)
    state.upsert(listing(420_000, "1"), near, "2026-10-04T17:00:00+02:00")       # početni popis
    state.meta_set("baseline:t", "2026-10-04T17:00:00+02:00")
    state.upsert(listing(410_000, "2"), near, "2026-10-05T07:00:00+02:00")       # nov oglas
    since = "2026-09-28T00:00:00+02:00"
    assert [r["source_id"] for r in state.near_misses_since(since)] == ["2"]
    assert state.counts_since(since) == {"t": {REJECT: 1}}
    state.close()


def test_device_split(tmp_path):
    names = lambda device: {s.name for s in Runner(tmp_path / "s.db", tmp_path, send=False, device=device).enabled_sources()}
    assert "njuskalo" not in names("github") and "nekretnine_hr" in names("github")
    assert names("redmi") == {"njuskalo"}


class QuietSource(FakeSource):
    name, label, daily = "quiet", "quiet", False
    baseline_report = False

    def fetch(self, mode, known_ids):
        QuietSource.modes.append(mode)
        return QuietSource.batches.pop(0)


def test_silent_baseline_and_reposted_old_ads(tmp_path, monkeypatch):
    import scraper.runner as runner_mod

    monkeypatch.setitem(runner_mod.ALL, "quiet", QuietSource)
    old = listing(sid="2")
    old.extra["stari_oglas"] = True
    cheaper = listing(280_000, "2")
    QuietSource.modes = []
    QuietSource.batches = [[listing(sid="1")],              # početak praćenja: ništa ne stiže
                           [listing(sid="1"), old, listing(sid="3", area=95)],  # stari ponovno objavljen + nov
                           [cheaper]]                        # stari sad jeftiniji
    sent = []

    def run_once():
        r = Runner(tmp_path / "s.db", tmp_path / "out", send=False, device="redmi")
        r.cfg["izvori"] = {"quiet": "redmi"}
        r._send_report = lambda *a, **k: sent.append(("report",))
        r._send_notifications = lambda state, items: sent.extend((x.source_id, h) for x, d, h in items)
        r.run(force=True)

    run_once()
    assert sent == []
    run_once()
    assert sent == [("3", "")]
    sent.clear()
    run_once()
    assert len(sent) == 1 and sent[0][0] == "2" and sent[0][1].startswith("📉")
    state = State(tmp_path / "s.db")
    assert state.meta_get("last_run") and [r["source_id"] for r in state.notified_since("2000")] == []
    state.close()


def test_redmi_watchdog(tmp_path):
    from datetime import timedelta

    redmi = State(tmp_path / "redmi.db")
    mails = []

    def check(minutes_ago):
        r = Runner(tmp_path / "s.db", tmp_path, send=False, redmi_db=tmp_path / "redmi.db")
        r.now = r.now.replace(hour=12)
        redmi.meta_set("last_run", (r.now - timedelta(minutes=minutes_ago)).isoformat(timespec="seconds"))
        redmi.conn.commit()
        r._email = lambda subject, *a, **k: mails.append(subject)
        state = State(tmp_path / "s.db")
        r._check_redmi(state)
        state.close()

    check(20)
    check(200)
    check(220)  # upozorenje samo jednom
    check(10)
    assert mails == ["Scraper: Redmi se ne javlja", "Scraper: Redmi se ponovno javlja"]
    redmi.close()


def test_same_property_rules():
    from scraper.dedupe import same_property
    from scraper.locations import Locator

    a = {"key": "a", "kind": HOUSE, "jls": "Krk", "price": 352_000, "area": 148, "title": "Kuća Krk", "settlement": ""}
    assert same_property({**a, "key": "b"}, a)                                     # isti (neokrugli) brojevi
    assert not same_property({**a, "key": "b", "area": 160}, a)                    # druga površina
    assert not same_property({**a, "key": "b", "jls": "Punat"}, a)                 # druga općina
    near = {**a, "key": "b", "price": 350_000, "area": 149}
    assert not same_property(near, a)                                              # blizu, ali bez dokaza
    assert same_property({**near, "settlement": "Vrh"}, {**a, "settlement": "Vrh"})  # isto naselje
    titled = {**near, "title": "Kamena kuća Linardići s pogledom"}
    assert same_property(titled, {**a, "title": "Linardići, kamena kuća, pogled na more"})
    cheaper = {**a, "key": "b", "price": 320_000, "settlement": "Vrh"}
    assert not same_property(cheaper, {**a, "settlement": "Vrh"})
    assert same_property(cheaper, {**a, "settlement": "Vrh"}, cheaper_ok=True)
    # Okrugli brojevi (350.000 €, 100 m²) traže dokaz; različita naselja nikad nisu isti oglas.
    r = {**a, "price": 350_000, "area": 100}
    assert not same_property({**r, "key": "b", "title": "Obiteljska kuća"}, r)
    loc = Locator()
    from scraper.dedupe import places
    vrh = {**a, "key": "b", "title": "Obiteljska kuća 140 m², Vrh, Pinezići, Krk"}
    grad = {**a, "title": "Višeobiteljska kuća Grad Krk, Centar, Krk"}
    places(vrh, loc), places(grad, loc)
    assert vrh["_places"] == {"vrh", "pinezici"} and grad["_places"] == set()
    selce = {**a, "key": "c", "jls": "Crikvenica", "title": "Selce, kuća"}
    dramalj = {**a, "jls": "Crikvenica", "title": "Dramalj, kuća"}
    places(selce, loc), places(dramalj, loc)
    assert not same_property(selce, dramalj)


def test_seen_on_other_portal(tmp_path, monkeypatch):
    import scraper.runner as runner_mod

    class Two(FakeSource):
        name, label, daily = "two", "two", False

        def fetch(self, mode, known_ids):
            return Two.batches.pop(0)

    monkeypatch.setitem(runner_mod.ALL, "two", Two)
    first = listing(sid="1", title="Kuća Punat, Stara Baška")
    same_elsewhere = listing(sid="9", title="Stara Baška kuća", source="two")
    cheaper_elsewhere = listing(285_000, sid="8", title="Stara Baška kuća", source="two")
    cheaper_elsewhere.settlement = first.settlement = same_elsewhere.settlement = "Stara Baška"
    Two.batches = [[listing(sid="0", area=60)], [first, same_elsewhere], [same_elsewhere, cheaper_elsewhere]]
    sent = []

    def run_once():
        r = Runner(tmp_path / "s.db", tmp_path / "out", send=False)
        r.cfg["izvori"] = {"two": True}
        r._send_report = lambda *a, **k: None
        r._send_notifications = lambda state, items: [
            (sent.append((x.source_id, h)), state.mark_notified(x.key, x.price, r.stamp)) for x, d, h in items]
        r.run(force=True)

    run_once()                      # početni popis
    run_once()                      # dva portala, isti oglas, isto pokretanje → jedna poruka
    assert sent == [("1", "")]
    run_once()                      # isti opet → ništa; jeftiniji → poruka s napomenom
    assert len(sent) == 2 and sent[1][0] == "8" and sent[1][1].startswith("📉 Već viđen")
    state = State(tmp_path / "s.db")
    assert [r["source_id"] for r in state.duplicates_since("2000")] == ["9"]
    state.close()


def test_short_description_keeps_text_reject(tmp_path, monkeypatch):
    """Odbijen zbog rečenice iz punog opisa; kasnije popis daje samo početak opisa → bez poruke."""
    import scraper.runner as runner_mod

    monkeypatch.setitem(runner_mod.ALL, "fake", FakeSource)
    part = listing(sid="4")
    part.description = "Prodaje se suvlasnički dio kuće (1/2) s okućnicom i parkingom."
    short = listing(sid="4")
    short.description = "Kuća u Puntu s parkingom."
    short.extra["opis_skracen"] = True
    FakeSource.modes = []
    FakeSource.batches = [[listing(sid="1")], [part], [short]]
    sent = []
    for _ in range(3):
        r = Runner(tmp_path / "s.db", tmp_path / "out", send=False)
        r.cfg["izvori"] = {"fake": True}
        r._send_report = lambda *a, **k: None
        r._send_notifications = lambda state, items: sent.extend(x.source_id for x, d, h in items)
        r.run(force=True)
    state = State(tmp_path / "s.db")
    assert sent == [] and state.get("t:4")["status"] == REJECT
    state.close()


def test_known_listing_gets_place_from_earlier_fetch(tmp_path, monkeypatch):
    """Popis bez mjesta (burza.com.hr): naselje i tekst lokacije dolaze iz ranijeg dohvata stranice oglasa."""
    import scraper.runner as runner_mod

    monkeypatch.setitem(runner_mod.ALL, "fake", FakeSource)
    first = listing(sid="5", title="Kuća s okućnicom")
    first.municipality, first.settlement, first.location_text = "", "Sveti Ivan, Općina Oprtalj", "Sveti Ivan, Općina Oprtalj"
    later = listing(sid="5", title="Kuća s okućnicom")
    later.municipality = ""
    FakeSource.modes = []
    FakeSource.batches = [[first], [later]]
    for _ in range(2):
        r = Runner(tmp_path / "s.db", tmp_path / "out", send=False)
        r.cfg["izvori"] = {"fake": True}
        r._send_report = lambda *a, **k: None
        r._send_notifications = lambda state, items: None
        r.run(force=True)
    assert later.location_text == "Sveti Ivan, Općina Oprtalj"
    state = State(tmp_path / "s.db")
    assert state.get("t:5")["status"] == REJECT
    state.close()
