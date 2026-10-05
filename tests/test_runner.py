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
                          [listing(sid="1"), listing(sid="3"), listing(380_000, "2")]]  # novi + snižen
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
                           [listing(sid="1"), old, listing(sid="3")],  # stari ponovno objavljen + nov
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
