"""Logika obavijesti (nov oglas, snižena cijena, početni popis) bez mreže."""

import json

from scraper import report
from scraper.db import State
from scraper.models import HOUSE, PASS, REJECT, WARN, Decision, Listing
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
    def names(device):
        return {s.name for s in Runner(tmp_path / "s.db", tmp_path, send=False, device=device).enabled_sources()}

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
        r._send_notifications = lambda state, items: [
            (sent.append((x.source_id, h)), state.mark_notified(x.key, x.price, r.stamp)) for x, d, h in items]
        r.run(force=True)

    run_once()
    assert sent == []
    run_once()
    assert sent == [("3", "")]
    sent.clear()
    run_once()
    assert len(sent) == 1 and sent[0][0] == "2" and sent[0][1].startswith("📉")
    state = State(tmp_path / "s.db")
    # Tiho zabilježeni (početak praćenja, stari oglas) nisu u poslanima; poslani jesu.
    assert state.meta_get("last_run") and sorted(r["source_id"] for r in state.notified_since("2000")) == ["2", "3"]
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
    # Redmi radi, ali ne može slati na Telegram (on nema mail): javlja GitHub, jednom.
    mails.clear()
    for _ in range(3):
        redmi.health_fail("telegram", "Unauthorized")
    redmi.conn.commit()
    check(10)
    check(10)
    assert mails == ["Scraper: Redmi ne može slati na Telegram"]
    redmi.health_ok("telegram", "t")
    redmi.conn.commit()
    check(10)
    assert mails[-1] == "Scraper: Redmi ponovno šalje na Telegram"
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
    # "Cijena na upit" (1 € / 100 €) na dva portala: isti po površini i naslovu; s cijenom nije isti.
    vila = {"key": "i", "kind": HOUSE, "jls": "Matulji", "price": 100, "area": 430, "settlement": "",
            "title": "MATULJI – EKSKLUZIVNA VILA OD 430 M², 8 MINUTA OD OPATIJE"}
    assert same_property({**vila, "key": "o", "price": 1}, vila)
    assert not same_property({**vila, "key": "o", "title": "Kuća s bazenom"}, vila)
    assert not same_property({**vila, "key": "o", "price": 390_000}, vila)


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


def test_ppv_new_year_reminder(tmp_path, monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import scraper.runner as runner_mod

    sent, mails = [], []

    class Tg:
        def send_text(self, text, **kw):
            sent.append(text)

    class FakeIspu:
        year = 2026

        def ppv_year(self):
            return self.year

    def runner(day):
        r = Runner(tmp_path / "s.db", tmp_path / "out", send=False)
        r.telegram, r._ispu = Tg(), ispu
        r._email = lambda subject, text, *a, **k: mails.append(subject)
        r.now = datetime.fromisoformat(day).replace(tzinfo=ZoneInfo("Europe/Zagreb"))
        return r

    monkeypatch.setattr(runner_mod, "PPV_YEAR", 2026)
    ispu = FakeIspu()
    state = State(tmp_path / "s.db")
    runner("2026-12-31T09:00")._ppv_reminder(state)
    assert sent == []                                             # još 2026.
    r = runner("2027-01-01T07:00")
    r._ppv_reminder(state)
    r._ppv_reminder(state)                                        # isti dan samo jednom
    assert len(sent) == 1 and "Nova godina" in sent[0] and mails == ["Scraper: osvježi PPV (2027)"]
    assert "razmisli o brisanju starih oglasa" in sent[0]
    ispu.year = 2027
    runner("2027-01-02T07:00")._ppv_reminder(state)
    runner("2027-01-03T07:00")._ppv_reminder(state)
    assert len(sent) == 2 and "Novi PPV (2027)" in sent[1] and mails[-1] == "Scraper: objavljen PPV 2027"
    state.close()


def test_mute_button(tmp_path, monkeypatch):
    """Gumb "Ne zanima me": pritisak se pročita pri pokretanju; za taj oglas i isti oglas na
    drugom portalu više ne stiže ništa (ni sniženje)."""
    import json

    import scraper.runner as runner_mod
    from scraper.notify import listing_markup, muted_markup

    x = listing(sid="7")
    buttons = json.loads(listing_markup(x))["inline_keyboard"][0]
    assert [b["url"] for b in buttons] == ["https://x"]           # "Ne zanima me" je reakcija 👎
    old_buttons = {"inline_keyboard": [[{"text": "Otvori oglas", "url": "https://x"},
                                        {"text": "🔕 Ne zanima me", "callback_data": "nz:t:7"}]]}

    class Tg:
        chat_id = "42"

        def __init__(self):
            self.edited, self.sent, self.confirmed = [], [], set()
            self.updates = [
                {"update_id": 10, "callback_query": {"id": "q1", "data": "nz:t:7",   # gumb starije poruke
                 "message": {"message_id": 5, "chat": {"id": 42}, "reply_markup": old_buttons}}},
                {"update_id": 11, "callback_query": {"id": "q2", "data": "nz:t:8", "message": {"message_id": 6, "chat": {"id": 99}}}},
            ]

        def get_updates(self, offset):            # kao Telegram: pomak potvrđuje sve manje brojeve
            if offset:
                self.confirmed |= {u["update_id"] for u in self.updates if u["update_id"] < offset}
                return [u for u in self.updates if u["update_id"] >= offset]
            return [u for u in self.updates if u["update_id"] not in self.confirmed]

        def edit_markup(self, chat, mid, markup):
            self.edited.append((mid, json.loads(markup)))

        def answer_callback(self, qid, text):
            raise RuntimeError("query is too old")        # stari upit: ne smeta

    monkeypatch.setitem(runner_mod.ALL, "fake", FakeSource)
    FakeSource.modes = []
    kamena = "Kamena kuća s konobom, Punat"               # isti oglas na dva portala (opisne riječi)
    FakeSource.batches = [[listing(sid="7", title=kamena), listing(sid="9", source="u", title=kamena)],
                          [listing(280_000, "7", title=kamena), listing(250_000, "9", source="u", title=kamena)]]
    tg, sent = Tg(), []

    def run_once():
        r = Runner(tmp_path / "s.db", tmp_path / "out", send=False)
        r.cfg["izvori"] = {"fake": True}
        r.telegram = tg
        r._send_report = lambda *a, **k: None
        r._send_notifications = lambda state, items: sent.extend(x.key for x, d, h in items)
        r._banks = r._tenders = lambda *a, **k: None
        r.run(force=True)

    run_once()                                            # početni popis + pritisak gumba
    state = State(tmp_path / "s.db")
    assert state.muted() == {"t:7"} and state.meta_get("telegram:offset") == "12"
    state.close()
    assert tg.edited[0][0] == 5 and tg.edited[0][1]["inline_keyboard"][0][0]["url"] == "https://x"
    info = json.loads(muted_markup({}, "t:7"))["inline_keyboard"][0][0]
    assert "makni 👎" in info["text"] and info["callback_data"] == "nz-info"
    run_once()                                            # oba snižena: ništa ne stiže
    assert sent == []
    state = State(tmp_path / "s.db")
    assert "u:9" in state.muted()                         # zapamćen i blizanac
    state.close()
    assert json.loads((tmp_path / "github.json").read_text())["utisani"] == ["t:7", "u:9"]
    # Slučajan dodir: poništenje vraća poruke i za blizanca, a gumb opet glasi "Ne zanima me".
    tg.updates = [{"update_id": 12, "callback_query": {"id": "q3", "data": "pz:t:7",
                   "message": {"message_id": 5, "chat": {"id": 42}, "reply_markup": json.loads(muted_markup({}, "t:7"))}}}]
    FakeSource.batches = [[listing(270_000, "7", title=kamena), listing(240_000, "9", source="u", title=kamena)]]
    run_once()
    state = State(tmp_path / "s.db")
    assert state.muted() == set() and state.meta_get("telegram:offset") == "13"
    state.close()
    assert tg.edited[-1][1]["inline_keyboard"] == []                   # poništeno: bez oznake
    assert sorted(sent) == ["t:7", "u:9"]                 # sniženja opet stižu
    # Pritisak s manjim brojem od zapamćenog (novi bot; nakon tjedan dana bez pritisaka broj je
    # nasumičan) ne smije se izgubiti.
    tg.updates = [{"update_id": 3, "callback_query": {"id": "q4", "data": "nz:t:7",
                   "message": {"message_id": 5, "chat": {"id": 42}, "reply_markup": json.loads(listing_markup(x))}}}]
    FakeSource.batches = [[listing(260_000, "7", title=kamena)]]
    run_once()
    state = State(tmp_path / "s.db")
    assert state.muted() == {"t:7"} and tg.confirmed >= {3}
    state.close()


def test_redmi_watches_github(tmp_path):
    import json
    from datetime import datetime
    from zoneinfo import ZoneInfo

    alerts = []

    def runner(now, last):
        (tmp_path / "github.json").write_text(json.dumps({"zadnje_pokretanje": last, "utisani": ["t:1"]}))
        r = Runner(tmp_path / "r.db", tmp_path / "out", send=False, device="redmi", seen_file=tmp_path / "seen.json.gz")
        r.now = datetime.fromisoformat(now).replace(tzinfo=ZoneInfo("Europe/Zagreb"))
        r._alert = lambda subject, text: alerts.append(subject)
        return r

    state = State(tmp_path / "r.db")
    assert runner("2026-10-07T12:00", "2026-10-07T11:40:00+02:00")._github_info()["utisani"] == {"t:1"}
    runner("2026-10-07T08:30", "2026-10-06T23:00:00+02:00")._check_github(state)   # prije 9 h: noć je normalna
    runner("2026-10-07T12:00", "2026-10-07T11:40:00+02:00")._check_github(state)
    assert alerts == []
    runner("2026-10-07T14:00", "2026-10-07T11:40:00+02:00")._check_github(state)
    runner("2026-10-07T14:20", "2026-10-07T11:40:00+02:00")._check_github(state)   # samo jednom
    runner("2026-10-07T15:00", "2026-10-07T14:55:00+02:00")._check_github(state)
    assert alerts == ["Scraper: GitHub ne radi", "Scraper: GitHub ponovno radi"]
    runner("2026-10-07T16:00", "2026-10-07T15:50:00")._check_github(state)        # bez zone: zagrebačko vrijeme
    runner("2026-10-07T16:00", "jučer")._check_github(state)                        # neispravno: bez pada
    assert len(alerts) == 2
    state.close()


def test_redmi_tells_its_own_download_problem_from_github_outage(tmp_path):
    """github.json se zamijeni pri svakom preuzimanju: kad je i on star, ne preuzima Redmi
    (internet, token), a ne GitHub – poruka to kaže."""
    import json
    import os
    from datetime import datetime
    from zoneinfo import ZoneInfo

    alerts = []
    path = tmp_path / "github.json"
    path.write_text(json.dumps({"zadnje_pokretanje": "2026-10-07T11:40:00+02:00"}))
    fetched = datetime(2026, 10, 7, 11, 45, tzinfo=ZoneInfo("Europe/Zagreb")).timestamp()
    os.utime(path, (fetched, fetched))
    r = Runner(tmp_path / "r.db", tmp_path / "out", send=False, device="redmi", seen_file=tmp_path / "seen.json.gz")
    r.now = datetime(2026, 10, 7, 14, 0, tzinfo=ZoneInfo("Europe/Zagreb"))
    r._alert = lambda subject, text: alerts.append((subject, text))
    state = State(tmp_path / "r.db")
    r._check_github(state)
    assert alerts[0][0] == "Scraper: Redmi ne preuzima stanje s GitHuba" and "07.10. u 11:45" in alerts[0][1]
    path.write_text(json.dumps({"zadnje_pokretanje": "2026-10-07T13:40:00+02:00"}))   # opet preuzima
    r._check_github(state)
    assert alerts[1][0] == "Scraper: Redmi ponovno preuzima stanje s GitHuba"
    state.close()


def test_corrupt_files_on_phone_do_not_crash(tmp_path):
    """Prekinut prijenos na Redmiju: skraćen seen.json.gz (EOFError) samo se zabilježi;
    sažetak se na GitHubu piše preko privremene datoteke."""
    import gzip
    import json

    from scraper import dedupe

    good = gzip.compress(json.dumps([]).encode())
    (tmp_path / "seen.json.gz").write_bytes(good[: len(good) // 2])
    r = Runner(tmp_path / "r.db", tmp_path / "out", send=False, device="redmi", seen_file=tmp_path / "seen.json.gz")
    state = State(tmp_path / "r.db")
    r._load_seen(state)
    assert any("nije učitan" in line for line in r.log_lines)
    (tmp_path / "seen.json.gz").unlink()
    r._load_seen(state)
    assert any("ne postoji" in line for line in r.log_lines)
    assert dedupe.export(state, tmp_path / "seen.json.gz") == 0
    assert json.loads(gzip.decompress((tmp_path / "seen.json.gz").read_bytes())) == []
    assert not list(tmp_path.glob("*.tmp"))
    state.close()


def test_price_drop_compared_to_notified_price(tmp_path):
    runner = Runner(tmp_path / "s.db", tmp_path, send=False)
    state = State(tmp_path / "s.db")
    ok = Decision(PASS, jls="Punat")
    state.upsert(listing(300_000), ok, "t1")
    state.mark_notified("t:1", 300_000, "t1")
    state.upsert(listing(320_000), ok, "t2")                                  # poskupio
    assert runner._notify_reason(listing(310_000), ok, state.get("t:1")) is None   # i dalje skuplji nego u poruci
    assert runner._notify_reason(listing(290_000), ok, state.get("t:1")) == "📉 Snižena cijena: 300.000 € → 290.000 €"
    state.close()


def test_project_units_and_town_names_are_not_duplicates():
    """Više jedinica istog projekta na istom portalu (bliske cijene) i kuće koje dijele samo
    ime mjesta u naslovu nisu ista nekretnina; ponovna objava (iste brojke) jest."""
    from scraper.dedupe import places, same_property
    from scraper.locations import Locator

    loc = Locator()

    def r(key, source, price, area, title, jls="Malinska-Dubašnica"):
        row = {"key": key, "source": source, "kind": HOUSE, "jls": jls, "price": price, "area": area, "title": title,
               "settlement": ""}
        places(row, loc)
        return row

    a = r("n:2704487", "nekretnine_hr", 350_000, 310, "Obiteljska vila Barušići, Malinska-Dubašnica")
    b = r("n:2704423", "nekretnine_hr", 352_000, 310, "Obiteljska vila Barušići, Malinska-Dubašnica")
    assert not same_property(a, b) and not same_property(a, b, cheaper_ok=True)        # dvije jedinice
    assert same_property(r("n:1", "nekretnine_hr", 352_000, 310, a["title"]), b)        # ponovna objava
    assert same_property(r("i:1", "index_oglasi", 351_000, 310, "Vila u Barušićima"), b)  # drugi portal, isto naselje
    baska1 = r("n:5", "nekretnine_hr", 360_000, 85, "Obiteljska kuća Baška, Baška", "Baška")
    baska2 = r("o:6", "oglasnik", 362_000, 85.5, "Obiteljska kuća Baška, Baška", "Baška")
    assert not same_property(baska1, baska2)                                            # samo ime mjesta


# --- svježi pregled koda (finiširanje, korak 4) ---

def _runs(tmp_path, monkeypatch, batches, configure=None):
    """Pokretanja s lažnim izvorom; vraća poslane (ključ, naslov) po pokretanju."""
    import scraper.runner as runner_mod

    monkeypatch.setitem(runner_mod.ALL, "fake", FakeSource)
    FakeSource.modes, FakeSource.batches = [], list(batches)
    out = []
    for i in range(len(batches)):
        sent = []
        r = Runner(tmp_path / "s.db", tmp_path / "out", send=False)
        r.cfg["izvori"] = {"fake": True}
        r._send_report = lambda *a, **k: None
        r._check_land = lambda *a, **k: None
        r._banks = r._tenders = r._ppv_reminder = lambda *a, **k: None
        r._send_notifications = lambda state, items, sent=sent: [
            (sent.append((x.key, h)), state.mark_notified(x.key, x.price, r.stamp)) for x, d, h in items]
        if configure:
            configure(r, i)
        try:
            r.run(force=True)
        except Killed:
            pass
        out.append(sent)
    return out


class Killed(BaseException):
    """Pokretanje prekinuto izvana (istek vremena posla, Android ugasi Termux)."""


def test_failed_send_does_not_lose_property_on_two_portals(tmp_path, monkeypatch):
    """Isti oglas na dva portala; slanje prvog ne uspije → sljedeće pokretanje ga ipak pošalje
    (drugi je zabilježen kao "isti kao prvi", ali poruka nije stigla)."""
    title = "Kamena kuća s konobom, Punat"
    a, b = listing(sid="1", title=title), listing(sid="2", source="u", title=title)

    def configure(r, i):
        if i == 1:                                    # Telegram ne radi: ništa se ne bilježi kao poslano
            r._send_notifications = lambda state, items: None

    sent = _runs(tmp_path, monkeypatch, [[listing(sid="0", area=60)], [a, b], [a, b]], configure)
    assert sent[2] == [("t:1", "")]


def test_list_only_data_keeps_detail_reject(tmp_path, monkeypatch):
    """index.hr i Njuškalo: odbijen prema stranici oglasa (vrsta, opis); sljedeći put samo
    popis (bez vrste i opisa) → ne smije stići "🔄 Sad odgovara"."""
    def detail(sid, subtype="", desc="", kind=HOUSE, title="Kuća Punat"):
        x = listing(sid=sid, title=title)
        x.kind, x.subtype, x.description = kind, subtype, desc
        if kind != HOUSE:
            x.area = 800
        return x

    def list_only(sid, **kw):
        x = detail(sid, **kw)
        x.subtype, x.description = "", ""
        x.extra["samo_popis"] = True
        return x

    from scraper.models import LAND
    first = [detail("2", subtype="Dvojna kuća"), detail("3", kind=LAND, subtype="Poljoprivredno zemljište", title="Zemljište Punat"),
             detail("4", desc="Prodaje se suvlasnički dio kuće 1/2.")]
    later = [list_only("2"), list_only("3", kind=LAND, title="Zemljište Punat"), list_only("4")]
    sent = _runs(tmp_path, monkeypatch, [[listing(sid="1")], first, later])
    assert sent[1] == [] and sent[2] == []
    state = State(tmp_path / "s.db")
    assert {state.get(f"t:{i}")["status"] for i in "234"} == {REJECT}
    state.close()


def test_placeholder_price_is_not_a_drop(tmp_path):
    """"Cijena na upit" (1 €) nije sniženje; pravo sniženje poslije toga stiže."""
    runner = Runner(tmp_path / "s.db", tmp_path, send=False)
    state = State(tmp_path / "s.db")
    ok = Decision(PASS, jls="Punat")
    state.upsert(listing(390_000), ok, "t1")
    state.mark_notified("t:1", 390_000, "t1")
    assert runner._notify_reason(listing(1), ok, state.get("t:1")) is None
    state.upsert(listing(1), ok, "t2")
    state.upsert(listing(390_000), ok, "t3")
    assert runner._notify_reason(listing(350_000), ok, state.get("t:1")) == "📉 Snižena cijena: 390.000 € → 350.000 €"
    # Cijena po m² (800 € × 120 m²) uspoređuje se kao ukupna.
    assert runner._notify_reason(listing(800), ok, state.get("t:1")) == "📉 Snižena cijena: 390.000 € → 96.000 €"
    state.close()


def test_deferred_listings_are_remembered_between_runs(tmp_path, monkeypatch):
    """Oglas koji izvor nije stigao otvoriti pamti se u bazi i predaje izvoru sljedeći put."""
    seen_pending = []

    def fetch(src, mode, known_ids):
        seen_pending.append([x.source_id for x in src.pending])
        src.deferred = [listing(sid="9")] if len(seen_pending) == 2 else []
        return FakeSource.batches.pop(0)

    monkeypatch.setattr(FakeSource, "fetch", fetch)
    _runs(tmp_path, monkeypatch, [[listing(sid="1")], [listing(sid="1")], [listing(sid="1")], [listing(sid="1")]])
    assert seen_pending == [[], [], ["9"], []]


def test_failed_reports_are_retried(tmp_path, monkeypatch):
    """Početni popis ili zbirna datoteka nisu stigli → ništa se ne bilježi kao poslano."""
    import scraper.runner as runner_mod

    monkeypatch.setitem(runner_mod.ALL, "fake", FakeSource)
    FakeSource.modes = []
    FakeSource.batches = [[listing(sid="1")], [listing(sid="1")], [listing(sid=str(i)) for i in range(2, 6)]]
    reports = []

    def run_once(ok):
        r = Runner(tmp_path / "s.db", tmp_path / "out", send=False)
        r.cfg["izvori"] = {"fake": True}
        r.cfg["obavijesti"]["max_poruka_po_pokretanju"] = 2
        r.telegram = object()                          # "postavljen" (šalje se zbirno)
        r._check_land = lambda *a, **k: None
        r._banks = r._tenders = r._ppv_reminder = lambda *a, **k: None
        r._send_report = lambda path, caption, *a, **k: (reports.append(caption), ok)[1]
        r.run(force=True)

    run_once(False)                                    # početni popis nije stigao
    assert FakeSource.modes == ["full"]
    run_once(True)                                     # ponovno cijelo područje i popis
    assert FakeSource.modes == ["full", "full"] and len(reports) == 2
    run_once(False)                                    # 4 nova > 2: zbirna datoteka nije stigla
    state = State(tmp_path / "s.db")
    assert state.get("t:1")["notified_at"].startswith("zbirno:")
    assert all(state.get(f"t:{i}")["notified_at"] is None for i in range(2, 6))
    state.close()


def test_failed_alert_is_retried(tmp_path):
    runner = Runner(tmp_path / "s.db", tmp_path, send=False)
    state = State(tmp_path / "s.db")

    class Src:
        name, label = "x", "x"

    results = [False, True]
    runner._alert = lambda subject, text: results.pop(0)
    for _ in range(4):
        runner._source_failed(state, Src(), RuntimeError("503"))
    assert results == []                               # 3. greška: nije stiglo; 4.: stiglo
    assert next(h for h in state.health_all() if h["source"] == "x")["alerted"]
    state.close()


def test_redmi_unmute_reaches_twins(tmp_path):
    """Redmi: "isti kao K" vrijedi samo dok je K na GitHubovu popisu utišanih."""
    state = State(tmp_path / "r.db")
    state.mute("njuskalo:5", "t", "isti kao t:7")
    state.mute("njuskalo:6", "t", "isti kao t:8")
    assert state.muted({"t:7"}) == {"t:7", "njuskalo:5"}
    assert state.muted(set()) == set()
    assert state.muted() == {"njuskalo:5", "njuskalo:6"}   # bez popisa s GitHuba: sve zapamćeno
    state.close()


# --- druga runda svježeg pregleda ---

def test_drop_after_price_on_request_phase(tmp_path):
    """390.000 € (poruka) → "cijena na upit" → 350.000 €: sniženje stiže."""
    runner = Runner(tmp_path / "s.db", tmp_path, send=False)
    state = State(tmp_path / "s.db")
    ok = Decision(PASS, jls="Punat")
    for placeholder, sid in ((1, "1"), (None, "2")):
        state.upsert(listing(390_000, sid), ok, "t1")
        state.mark_notified(f"t:{sid}", 390_000, "t1")
        state.upsert(listing(placeholder, sid), ok, "t2")
        assert runner._notify_reason(listing(390_000, sid), ok, state.get(f"t:{sid}")) is None
        assert runner._notify_reason(listing(350_000, sid), ok, state.get(f"t:{sid}")) == \
            "📉 Snižena cijena: 390.000 € → 350.000 €"
    state.close()


def test_corrupt_redmi_db_does_not_stop_run(tmp_path, monkeypatch):
    (tmp_path / "redmi.db").write_bytes(b"nije baza " * 200)
    mails = []
    sent = _runs(tmp_path, monkeypatch, [[listing(sid="1")], [listing(sid="1"), listing(sid="2")]],
                 lambda r, i: (setattr(r, "redmi_db", tmp_path / "redmi.db"),
                               setattr(r, "_email", lambda subject, *a, **k: mails.append(subject))))
    assert sent[1] == [("t:2", "")]
    assert mails.count("Scraper: stanje s Redmija je oštećeno") == 1          # jednom, ne svako pokretanje


def test_reserve_run_skipped_while_main_trigger_works(tmp_path, monkeypatch):
    """GitHubov raspored (rezerva) ne radi ništa dok cron-job.org redovno pokreće."""
    from datetime import timedelta

    def configure(r, i):
        if i == 1:
            r.now = r.now + timedelta(minutes=10)
            r.run = lambda force=False, reserve=True, run=r.run: run(force, reserve)
        if i == 2:
            r.now = r.now + timedelta(minutes=45)
            r.run = lambda force=False, reserve=True, run=r.run: run(force, reserve)

    _runs(tmp_path, monkeypatch, [[listing(sid="1")], [listing(sid="1")], [listing(sid="1")]], configure)
    assert FakeSource.modes == ["full", "incremental"]           # drugo (10 min kasnije) preskočeno


def test_reserve_runs_every_slot_while_main_trigger_is_down(tmp_path, monkeypatch):
    """cron-job.org ne radi: rezerva se uspoređuje sa zadnjim glavnim pokretanjem, ne sa
    svojim, pa radi u svakom terminu (20 min), a ne u svakom drugom."""
    from datetime import timedelta

    def configure(r, i):
        if i:                                                     # rezerva 40, 60 i 80 min poslije
            r.now = r.now + timedelta(minutes=20 + 20 * i)
            r.stamp = r.now.isoformat(timespec="seconds")
            r.run = lambda force=False, reserve=True, run=r.run: run(force, reserve)

    _runs(tmp_path, monkeypatch, [[listing(sid="1")]] * 4, configure)
    assert FakeSource.modes == ["full", "incremental", "incremental", "incremental"]


def test_telegram_button_url_and_photo_timeout(monkeypatch):
    import json

    import requests

    from scraper.notify import Telegram, _button, listing_markup

    url = json.loads(_button("https://www.dobrinj.hr/dokumenti/Natječaj za prodaju.pdf"))["inline_keyboard"][0][0]["url"]
    assert url == "https://www.dobrinj.hr/dokumenti/Natje%C4%8Daj%20za%20prodaju.pdf"
    x = listing()
    x.url = "https://x.hr/a b?c=%20"
    assert json.loads(listing_markup(x))["inline_keyboard"][0][0]["url"] == "https://x.hr/a%20b?c=%20"

    calls = []
    tg = Telegram("t", "1")

    def call(method, data, files=None):
        calls.append(method)
        if method == "sendPhoto":
            raise requests.Timeout("slika")
        return {"ok": True}
    monkeypatch.setattr(tg, "_call", call)
    x.image_url = "https://x.hr/slika.jpg"
    tg.send_listing(x, Decision(PASS, jls="Punat"))
    assert calls == ["sendPhoto", "sendMessage"]


# --- treća runda ---

def test_price_on_request_without_price_is_seen(tmp_path, monkeypatch):
    """"Cijena na upit" bez cijene (None) na dva portala → jedna poruka."""
    title = "Kamena kuća s konobom, Punat"
    a, b = listing(None, "1", title=title), listing(None, "2", title=title, source="u")
    sent = _runs(tmp_path, monkeypatch, [[listing(sid="0", area=60)], [a, b]])
    assert sent[1] == [("t:1", "")]


def test_failed_sends_do_not_hide_property_through_copy_chain(tmp_path, monkeypatch):
    """A neposlan, B "isti kao A", C "isti kao B" (Telegram ne radi dva pokretanja) → kad
    proradi, stiže jedna poruka."""
    title = "Kamena kuća s konobom, Punat"
    a, b, c = listing(sid="1", title=title), listing(sid="2", source="u", title=title), listing(sid="3", source="v", title=title)

    def configure(r, i):
        if i in (1, 2):
            r._send_notifications = lambda state, items: None

    sent = _runs(tmp_path, monkeypatch, [[listing(sid="0", area=60)], [a, b], [a, b, c], [a, b, c]], configure)
    assert len(sent[3]) == 1


def test_mute_does_not_spread_to_cheaper_other_house(tmp_path, monkeypatch):
    """Utišana kuća 290.000 €; nova kuća iste površine u istom mjestu za 240.000 € (možda druga
    nekretnina) stiže kao "već viđen … sad jeftiniji", ne utiša se."""
    first = listing(290_000, "1", title="Obiteljska kuća, Stara Baška")
    other = listing(240_000, "2", title="Kamena kuća za adaptaciju, Stara Baška", source="u")
    first.settlement = other.settlement = "Stara Baška"

    def configure(r, i):
        if i == 2:
            st = State(tmp_path / "s.db")
            st.mute("t:1", "x", "gumb")
            st.close()

    first_cheaper = listing(280_000, "1", title="Obiteljska kuća, Stara Baška")
    first_cheaper.settlement = "Stara Baška"
    sent = _runs(tmp_path, monkeypatch, [[listing(sid="0", area=60)], [first], [first_cheaper, other]], configure)
    assert sent[1] == [("t:1", "")]
    # Utišana snižena (280.000) ne stiže; druga kuća (240.000) stiže s napomenom.
    assert [k for k, _ in sent[2]] == ["u:2"] and sent[2][0][1].startswith("📉 Već viđen")


def test_known_listing_keeps_area_from_listing_page(tmp_path, monkeypatch):
    """burza: površina iz kratkog isječka (80 m²) ne prepisuje onu sa stranice oglasa (1.200 m²)."""
    from scraper.models import LAND

    def land(price, area, from_text):
        x = listing(price, "7", area=area, title="Građevinsko zemljište, Punat")
        x.kind, x.subtype = LAND, "Građevinsko zemljište"
        if from_text:
            x.extra["povrsina_iz_teksta"] = True
        return x

    sent = _runs(tmp_path, monkeypatch, [[listing(sid="0", area=60)], [land(150_000, 1200, False)],
                                         [land(150_000, 80, True)], [land(120_000, 80, True)]])
    assert sent[3] and sent[3][0][1].startswith("📉 Snižena cijena")
    state = State(tmp_path / "s.db")
    assert state.get("t:7")["area"] == 1200
    state.close()


# --- četvrta runda ---

def test_round_area_glued_to_unit_is_not_a_shared_word():
    from scraper.dedupe import same_property

    a = {"key": "a:1", "source": "a", "kind": "zemljiste", "jls": "Crikvenica", "price": 100_000, "area": 500,
         "title": "Zemljište Crikvenica, 500m2"}
    b = dict(a, key="b:2", source="b", title="Zemljište Crikvenica, 500m2")
    assert not same_property(a, b)


def test_silent_rejected_listing_arrives_when_it_starts_matching(tmp_path, monkeypatch):
    """Tiho početno čitanje: odbijen oglas se ne bilježi kao viđen, pa kad počne odgovarati
    (izmjena oglasa ili pravila) stiže "🔄 Sad odgovara" – i njegova kopija na drugom portalu
    nije blokirana."""
    import scraper.runner as runner_mod

    monkeypatch.setitem(runner_mod.ALL, "quiet", QuietSource)
    QuietSource.modes = []
    QuietSource.batches = [[listing(300_000, "1", area=60)], [listing(300_000, "1", area=120)]]   # ispravljena površina
    sent = []
    for _ in range(2):
        r = Runner(tmp_path / "s.db", tmp_path / "out", send=False)
        r.cfg["izvori"] = {"quiet": True}
        r._check_land = lambda *a, **k: None
        r._banks = r._tenders = r._ppv_reminder = lambda *a, **k: None
        r._send_notifications = lambda state, items: sent.extend((x.key, h) for x, d, h in items)
        r.run(force=True)
    assert sent and sent[0][0] == "t:1" and "Sad odgovara" in sent[0][1]


def test_old_silent_rejected_rows_are_released_once(tmp_path):
    state = State(tmp_path / "s.db")
    state.upsert(listing(450_000, "1"), Decision(REJECT, ["x"]), "t1")
    state.mark_notified("t:1", 450_000, "tiho:t1")
    state.upsert(listing(300_000, "2"), Decision(PASS, jls="Punat"), "t1")
    state.mark_notified("t:2", 300_000, "tiho:t1")
    state.close()
    r = Runner(tmp_path / "s.db", tmp_path / "out", send=False)
    r.cfg["izvori"] = {}
    r._banks = r._tenders = r._ppv_reminder = lambda *a, **k: None
    r.run(force=True)
    state = State(tmp_path / "s.db")
    assert state.get("t:1")["notified_at"] is None and state.get("t:2")["notified_at"] == "tiho:t1"
    state.close()


def test_failed_send_is_retried_even_if_portal_no_longer_lists_it(tmp_path, monkeypatch):
    calls = []

    class Tg:
        chat_id = "1"
        fail = True

        def send_listing(self, x, d, h):
            if Tg.fail:
                raise RuntimeError("502")
            calls.append(x.key)

        def send_text(self, *a, **k):
            pass

        def send_document(self, *a, **k):
            pass

    def configure(r, i):
        r.telegram = Tg()
        r._send_notifications = runner_mod_send.__get__(r)
        Tg.fail = i == 1

    runner_mod_send = Runner._send_notifications
    _runs(tmp_path, monkeypatch, [[listing(sid="0", area=60)], [listing(sid="1")], [listing(sid="2")]], configure)
    assert sorted(calls) == ["t:1", "t:2"]                     # t:1 više nije na popisu, a ipak stiže


def test_weekly_report_retried_when_mail_fails(tmp_path):
    """Mail ne prolazi u ponedjeljak: izvještaj se ne bilježi kao poslan, nego se šalje pri
    sljedećem redovnom pokretanju; nakon dva dana neuspjeha stiže upozorenje."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    class Mail:
        ok = False

        def __init__(self):
            self.sent = []

        def send(self, subject, *a, **k):
            if not self.ok:
                raise OSError("SMTP: Connection unexpectedly closed")
            self.sent.append(subject)

    mail = Mail()
    r = Runner(tmp_path / "s.db", tmp_path, send=False)
    r.email, r.now = mail, datetime(2026, 10, 12, 7, 15, tzinfo=ZoneInfo("Europe/Zagreb"))
    r.stamp = r.now.isoformat(timespec="seconds")
    r._plan_decisions = lambda: None                            # bez mreže (tests/test_planwatch.py)
    assert r.weekly() is False and "NIJE poslan" in r.log_lines[-1]
    state = State(tmp_path / "s.db")
    assert state.meta_get("tjedni:neposlan") == r.stamp
    r._retry_weekly(state)                                      # mail i dalje ne radi
    assert state.meta_get("tjedni:neposlan") and mail.sent == []
    mail.ok = True
    r._retry_weekly(state)
    assert mail.sent == ["Scraper: tjedni izvještaj 12.10.2026."] and not state.meta_get("tjedni:neposlan")
    r._retry_weekly(state)
    assert len(mail.sent) == 1                                  # samo jednom

    # Poslan i naredbom "tjedni" nakon neuspjeha u ponedjeljak: redovno pokretanje ne šalje opet.
    state.meta_set("tjedni:neposlan", r.stamp)
    r._retry_weekly(state)
    assert len(mail.sent) == 1 and not state.meta_get("tjedni:neposlan")

    # Dva dana neuspjeha: upozorenje, pa stanka do sljedećeg tjedna (ne pokušava svakih 20 min).
    alerts = []
    r._alert = lambda subject, text: alerts.append(subject) or True
    state.meta_set("tjedni:tjedan", "2026-40")
    state.meta_set("tjedni:neposlan", (r.now - timedelta(days=3)).isoformat())
    r._retry_weekly(state)
    assert alerts == ["Scraper: tjedni izvještaj nije poslan"] and not state.meta_get("tjedni:neposlan")
    r._retry_weekly(state)
    assert len(mail.sent) == 1 and len(alerts) == 1
    state.close()


def test_weekly_retry_reads_plan_decisions_once(tmp_path):
    """Ponovno slanje istog tjedna koristi isto čitanje odluka o planovima."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from scraper import planwatch

    class Mail:
        ok = False

        def send(self, subject, *a, **k):
            if not self.ok:
                raise OSError("SMTP")

    r = Runner(tmp_path / "s.db", tmp_path, send=False)
    r.email, r.now = Mail(), datetime(2026, 10, 12, 7, 15, tzinfo=ZoneInfo("Europe/Zagreb"))
    crawls = []
    r._plan_decisions = lambda: crawls.append(1) or planwatch.Result(
        [planwatch.PlanDecision("Omišalj", "Odluka o donošenju UPU 1 Omišalj", "https://x/1")], 5, [],
        {planwatch.SEEN_KEY: '["https://x/1"]'})
    assert r.weekly(record=False) is False and r.weekly(record=False) is False
    r.email.ok = True
    assert r.weekly(record=False) is True and len(crawls) == 1
    state = State(tmp_path / "s.db")
    assert state.meta_get(planwatch.SEEN_KEY) == '["https://x/1"]'
    state.close()


# --- peta runda (ubrizgavanje kvarova) ---

def test_one_bad_listing_does_not_stop_the_run(tmp_path, monkeypatch):
    """Portal promijeni jedno polje: oglas koji se ne da obraditi preskače se, ostali stižu;
    kad se ne da obraditi većina, to je greška izvora (upozorenje nakon 3), a ne pad pokretanja."""
    import scraper.runner as runner_mod

    real = runner_mod.evaluate

    def evaluate(x, *a, **k):
        if x.title.startswith("pokvaren"):
            raise TypeError("'<' not supported between instances of 'str' and 'int'")
        return real(x, *a, **k)

    monkeypatch.setattr(runner_mod, "evaluate", evaluate)
    bad = [listing(sid=f"9{i}", title=f"pokvaren {i}") for i in range(3)]
    sent = _runs(tmp_path, monkeypatch, [[listing(sid="0", area=60)], [bad[0], listing(sid="1"), listing(sid="2")], bad])
    assert sorted(k for k, _ in sent[1]) == ["t:1", "t:2"]
    state = State(tmp_path / "s.db")
    health = next(h for h in state.health_all() if h["source"] == "fake")
    assert health["failures"] == 1 and "3 od 3 oglasa" in health["last_error"]
    assert state.meta_get("last_run")                          # pokretanje je završilo
    state.close()


def test_listing_survives_run_killed_before_sending(tmp_path, monkeypatch):
    """Pokretanje stane nakon spremanja oglasa, a prije slanja: sljedeće ga pošalje i kad ga
    portal više ne prikazuje (novi su ga pomaknuli dalje od pročitanih stranica)."""
    def configure(r, i):
        if i == 1:
            def killed(state, items):
                raise Killed()
            r._send_notifications = killed

    sent = _runs(tmp_path, monkeypatch, [[listing(sid="0", area=60)], [listing(sid="1")], [listing(sid="0", area=60)]],
                 configure)
    assert [k for k, _ in sent[2]] == ["t:1"]


def test_alert_falls_back_to_telegram_when_mail_fails(tmp_path):
    runner = Runner(tmp_path / "s.db", tmp_path, send=False)
    texts = []

    class Tg:
        def send_text(self, text, **k):
            texts.append(text)

    class Mail:
        ok = False

        def send(self, *a, **k):
            if not self.ok:
                raise OSError("535 Username and Password not accepted")

    runner.telegram, runner.email = Tg(), Mail()
    assert runner._alert("Scraper: izvor x ne radi", "503") is True and "izvor x ne radi" in texts[0]
    runner.email.ok = True
    assert runner._alert("Scraper: izvor y ne radi", "503") is True and len(texts) == 1   # mail prošao
    runner.email = None                                       # Redmi: bez maila
    assert runner._alert("Scraper: GitHub ne radi", "") is True and len(texts) == 2


def test_telegram_down_is_reported_by_mail_once(tmp_path):
    runner = Runner(tmp_path / "s.db", tmp_path, send=False)
    mails = []
    runner.email = object()
    runner._email = lambda subject, *a, **k: mails.append(subject) or True
    state = State(tmp_path / "s.db")
    for _ in range(5):
        runner._telegram_health(state, "RuntimeError: Telegram sendMessage: 403 Forbidden: bot was blocked by the user")
    assert mails == ["Scraper: Telegram ne prima poruke"]
    runner._telegram_health(state, None)
    runner._telegram_health(state, None)
    assert mails == ["Scraper: Telegram ne prima poruke", "Scraper: Telegram ponovno radi"]
    state.close()


def test_telegram_rejected_message_sent_as_plain_text_and_long_flood_wait(monkeypatch):
    """Telegram odbije poruku (400: neispravan HTML, adresa gumba): ista poruka stiže kao
    običan tekst s adresom. Dugo čekanje (429, retry_after 900 s) ne zaustavlja pokretanje."""
    import pytest

    from scraper import notify
    from scraper.notify import Telegram

    posts, sleeps = [], []

    class Resp:
        def __init__(self, status, body):
            self.status_code, self.body, self.headers, self.text = status, body, {"content-type": "application/json"}, ""

        def json(self):
            return self.body

    def post(url, data=None, files=None, timeout=None):
        posts.append(dict(data))
        if "parse_mode" in data:
            return Resp(400, {"ok": False, "description": "Bad Request: BUTTON_URL_INVALID"})
        return Resp(200, {"ok": True})

    monkeypatch.setattr(notify.requests, "post", post)
    monkeypatch.setattr(notify.time, "sleep", sleeps.append)
    tg = Telegram("t", "1")
    tg.send_text("<b>Natječaj</b> – k.č. 12 &amp; 13", url="javascript:alert(1)")
    assert posts[-1]["text"] == "Natječaj – k.č. 12 & 13\njavascript:alert(1)" and "reply_markup" not in posts[-1]
    x = listing()
    tg.send_listing(x, Decision(PASS, jls="Punat"))
    assert "parse_mode" not in posts[-1] and posts[-1]["text"].endswith("https://x")

    monkeypatch.setattr(notify.requests, "post", lambda *a, **k: Resp(429, {"ok": False, "parameters": {"retry_after": 900}}))
    with pytest.raises(RuntimeError, match="429"):
        tg.send_text("x")
    assert all(s < 60 for s in sleeps)

def test_unsent_keeps_first_time_and_expires_after_a_week(tmp_path):
    from datetime import timedelta

    runner = Runner(tmp_path / "s.db", tmp_path, send=False)
    state = State(tmp_path / "s.db")
    ok = Decision(PASS, jls="Punat")
    state.upsert(listing(), ok, "t1")
    first = (runner.now - timedelta(days=6)).isoformat(timespec="seconds")
    state.meta_set("neposlano", json.dumps([{"oglas": listing().to_dict(), "odluka": {"status": PASS, "jls": "Punat"},
                                            "naslov": "", "od": first}]))
    runner._prev_unsent = runner._load_unsent(state)
    runner._remember_unsent(state, runner._prev_unsent)       # ponovno ne uspije: "od" ostaje prvo vrijeme
    assert json.loads(state.meta_get("neposlano"))[0]["od"] == first
    seen = runner._load_seen(state)
    assert [x.key for x, _, _ in runner._unsent(state, seen, set())] == ["t:1"]
    runner.now += timedelta(days=2)                            # više od tjedan dana: odustaje se
    assert runner._unsent(state, seen, set()) == []
    state.close()


# --- šesta runda (simulacija tjedana rada) ---

def test_failed_price_drop_is_retried(tmp_path, monkeypatch):
    """Sniženje već javljenog oglasa ne prođe (Telegram ne radi): stiže sljedeći put, iako
    je cijena u bazi već nova i portal ga više ne prikazuje kao promjenu."""
    calls = []

    class Tg:
        chat_id = "1"
        fail = False

        def send_listing(self, x, d, h):
            if Tg.fail:
                raise RuntimeError("502")
            calls.append((x.key, h))

        def send_text(self, *a, **k):
            pass

        def send_document(self, *a, **k):
            pass

    def configure(r, i):
        r.telegram = Tg()
        r._send_notifications = Runner._send_notifications.__get__(r)
        Tg.fail = i == 2

    batches = [[listing(sid="0", area=60)], [listing(287_400, "1")], [listing(259_000, "1")], [listing(259_000, "1")]]
    _runs(tmp_path, monkeypatch, batches, configure)
    assert [k for k, _ in calls] == ["t:1", "t:1"] and calls[1][1].startswith("📉")


def test_luxury_on_request_stays_rejected_with_list_only_data():
    from scraper.models import WARN

    prev = {"reasons": json.dumps(["cijena na upit – luksuzna, procjena ≈ 900.000 € (medijan traženih Opatija: 3.000 €/m²)"])}
    d = Decision(WARN, warnings=["cijena na upit – procjena ≈ 900.000 €"], jls="Opatija")
    assert Runner._keep_text_reject(d, prev, on_request=True).status == REJECT
    assert Runner._keep_text_reject(d, prev, on_request=False) is d        # sad ima cijenu: nova odluka


def test_unmute_reaches_copy_of_copy(tmp_path):
    state = State(tmp_path / "s.db")
    state.mute("t:1", "t", "gumb")
    state.mute("u:2", "t", "isti kao t:1")
    state.mute("v:3", "t", "isti kao u:2")
    state.mute("w:4", "t", "gumb")
    state.unmute("t:1")
    assert state.muted() == {"w:4"}
    state.close()


def test_pricier_lookalike_after_raise_is_a_different_house(tmp_path):
    """A je javljen za 306.200 €, zatim poskupio na 324.600 €. Druga kuća iste površine za
    310.300 € nije ni jeftinija ni iste cijene – stiže kao nova, ne kao "već viđen"."""
    runner = Runner(tmp_path / "s.db", tmp_path, send=False)
    state = State(tmp_path / "s.db")
    ok = Decision(PASS, jls="Punat")
    kamena = "Kamena kuća s konobom, Punat"
    state.upsert(listing(306_200, "1", 126, kamena), ok, "t1")
    state.mark_notified("t:1", 306_200, "t1")
    state.upsert(listing(324_600, "1", 126, kamena), ok, "t2")
    seen = runner._load_seen(state)
    assert runner._check_seen(state, seen, listing(310_300, "2", 124, kamena, source="u"), ok, None, "") == ""
    seen = runner._load_seen(state)
    assert runner._check_seen(state, seen, listing(306_500, "3", 125, kamena, source="v"), ok, None, "") is None
    seen = runner._load_seen(state)
    assert "sad jeftiniji" in runner._check_seen(state, seen, listing(280_000, "4", 126, kamena, source="w"),
                                                 ok, None, "")
    state.close()


def test_seen_copy_with_existing_row_is_marked(tmp_path):
    """Kopija koja već ima red (npr. nakon poništenja "Ne zanima me") bilježi se kao viđena."""
    runner = Runner(tmp_path / "s.db", tmp_path, send=False)
    state = State(tmp_path / "s.db")
    ok = Decision(PASS, jls="Punat")
    kamena = "Kamena kuća s konobom, Punat"
    state.upsert(listing(300_000, "1", title=kamena), ok, "t1")
    state.mark_notified("t:1", 300_000, "t1")
    b = listing(300_000, "2", title=kamena, source="u")
    state.upsert(b, ok, "t2")                                   # red postoji, nije javljen
    old = state.get("u:2")
    assert runner._check_seen(state, runner._load_seen(state), b, ok, old, "") is None
    assert state.get("u:2")["notified_at"] == "dup:t:1"
    state.close()


def test_weekly_report_from_first_monday_run_once(tmp_path):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    sent = []
    runner = Runner(tmp_path / "s.db", tmp_path, send=False)
    runner.weekly = lambda record=True: sent.append(runner.now) or True
    state = State(tmp_path / "s.db")
    tz = ZoneInfo("Europe/Zagreb")
    for day, hour in ((7, 9), (12, 7), (12, 7), (13, 7)):       # srijeda (prvi put), pon, pon, uto
        runner.now = datetime(2026, 10, day, hour, tzinfo=tz)
        runner._retry_weekly(state)
    assert [d.day for d in sent] == [12]
    runner.now += timedelta(days=7)                              # sljedeći tjedan: ponedjeljak propušten
    runner.now = datetime(2026, 10, 20, 7, tzinfo=tz)            # utorak
    runner._retry_weekly(state)
    assert [d.day for d in sent] == [12, 20]                     # nadoknađen
    state.close()


def test_dislike_reaction_mutes_and_removal_unmutes(tmp_path):
    """👎 na poruci oglasa = "Ne zanima me" (Telegram je čuva, ne treba čekati), maknuta 👎 =
    poništenje. Reakcija nosi samo broj poruke; poruka koju je poslao Redmi, a GitHub je još
    ne zna, čeka sljedeće pokretanje."""
    class Tg:
        chat_id = "42"
        edited = []

        def edit_markup(self, chat, mid, markup):
            self.edited.append((mid, json.loads(markup)))

        def get_updates(self, offset, wait=0):
            return []

    def reaction(uid, mid, old, new):
        return {"update_id": uid, "message_reaction": {
            "chat": {"id": 42}, "message_id": mid, "user": {"id": 1}, "date": 0,
            "old_reaction": [{"type": "emoji", "emoji": e} for e in old],
            "new_reaction": [{"type": "emoji", "emoji": e} for e in new]}}

    r = Runner(tmp_path / "s.db", tmp_path, send=False)
    r.telegram = Tg()
    state = State(tmp_path / "s.db")
    state.upsert(listing(sid="7"), Decision(PASS, jls="Punat"), "t1")
    state.remember_message(501, "t:7", "t1")
    r._handle_updates(state, [reaction(1, 501, [], ["👎"])])
    assert state.muted() == {"t:7"}
    assert Tg.edited[-1][0] == 501 and Tg.edited[-1][1]["inline_keyboard"][0][0]["url"] == "https://x"
    r._handle_updates(state, [reaction(2, 501, ["👎"], ["❤"])])          # zamijenjena drugom reakcijom
    assert state.muted() == set()
    r._handle_updates(state, [reaction(3, 999, [], ["👎"])])              # poruka još nepoznata
    assert state.muted() == set() and json.loads(state.meta_get("reakcije:cekaju"))
    state.remember_message(999, "t:7", "t2")                              # stiglo stanje s Redmija
    r._handle_updates(state, [])                                          # i bez novih ažuriranja
    assert state.muted() == {"t:7"} and json.loads(state.meta_get("reakcije:cekaju")) == []
    state.close()


def test_send_listing_returns_message_id(monkeypatch):
    from scraper import notify
    from scraper.notify import Telegram

    class Resp:
        status_code, headers, text = 200, {"content-type": "application/json"}, ""

        def json(self):
            return {"ok": True, "result": {"message_id": 321}}

    monkeypatch.setattr(notify.requests, "post", lambda *a, **k: Resp())
    monkeypatch.setattr(notify.time, "sleep", lambda s: None)
    assert Telegram("t", "1").send_listing(listing(), Decision(PASS, jls="Punat")) == [321]


def test_long_caption_continues_in_second_message(monkeypatch):
    """Opis fotografije je ograničen: što ne stane ide u drugu poruku (odgovor na prvu, bez
    zvuka), a obje se pamte za 👎. Bez fotografije sve ide u jednu poruku."""
    from scraper.notify import CAPTION, Telegram

    x = listing()
    x.image_url = "https://x.hr/slika.jpg"
    x.extra.update(ppv="🏛 " + "PPV redak " * 40, prosjek="📐 " + "prosjek područja " * 20,
                   usporedba="💰 " + "medijan mjesta " * 20)
    d = Decision(WARN, warnings=["⚠ prvo upozorenje", "drugo upozorenje " * 8], jls="Punat")
    posts = []
    tg = Telegram("t", "1")

    def call(method, data, files=None):
        posts.append((method, data))
        return {"ok": True, "result": {"message_id": 700 + len(posts)}}
    monkeypatch.setattr(tg, "_call", call)
    assert tg.send_listing(x, d) == [701, 702]
    (m1, first), (m2, second) = posts
    assert m1 == "sendPhoto" and len(first["caption"]) <= CAPTION and "📐" in first["caption"]
    assert m2 == "sendMessage" and "💰" in second["text"] and "Kuća Punat" in second["text"]
    assert "PPV redak" in first["caption"] and "💰" not in first["caption"]
    assert json.loads(second["reply_parameters"])["message_id"] == 701 and second["disable_notification"] == "true"
    assert "drugo upozorenje" in first["caption"] + second["text"]

    posts.clear()
    x.image_url = ""
    assert tg.send_listing(x, d) == [701]
    assert "💰" in posts[0][1]["text"] and "PPV redak" in posts[0][1]["text"]

    # Samo naslov oglasa ne stane: bez druge poruke.
    posts.clear()
    y = listing()
    y.image_url = "https://x.hr/slika.jpg"
    y.extra["ppv"] = "🏛 " + "p" * (CAPTION - 90)
    assert tg.send_listing(y, Decision(PASS, jls="Punat")) == [701] and len(posts) == 1


def test_reaction_on_second_message_mutes_listing(tmp_path):
    from scraper.db import State

    state = State(tmp_path / "s.db")
    for mid in (701, 702):
        state.remember_message(mid, "t:7", "t1")
    assert state.message_key(702) == "t:7"


def test_parcelation_listing_keeps_arriving_with_list_only_data(tmp_path, monkeypatch):
    """Zemljište izvan cijene i površine stiglo je jer opis spominje parcelaciju. Sljedeći put
    portal daje samo popis (bez opisa): sniženje i dalje stiže."""
    from scraper.models import LAND

    def plot(price, partial=False):
        x = Listing(source="t", source_id="5", url="https://x", title="Zemljište Punat", kind=LAND,
                    subtype="Građevinsko zemljište", price=price, area=5_000, county="Primorsko-goranska",
                    municipality="Punat", description="" if partial else "Moguća parcelacija na tri čestice.")
        if partial:
            x.extra["samo_popis"] = True
        return x

    sent = _runs(tmp_path, monkeypatch, [[listing(sid="0", area=60)], [plot(900_000)], [plot(820_000, partial=True)]])
    assert [k for k, _ in sent[1]] == ["t:5"]
    assert [k for k, _ in sent[2]] == ["t:5"] and sent[2][0][1].startswith("📉")


def test_renovation_category_kept_for_list_only_price_drop(tmp_path, monkeypatch):
    """Kuća za obnovu prepoznata iz opisa: sniženje s popisa (bez opisa) uspoređuje se i dalje
    s kućama za obnovu, ne s useljivima."""
    def ruin(price, partial=False):
        x = listing(price=price, sid="5", title="Kuća Punat", area=110)
        if partial:
            x.extra["samo_popis"] = True
        else:
            x.description = "Stara kamena kuća za obnovu."
        return x

    seen = {}

    def configure(r, i):
        def send(state, items):
            for x, d, h in items:
                seen[i] = x.extra.get("kategorija")
                state.mark_notified(x.key, x.price, r.stamp)
        r._send_notifications = send
    _runs(tmp_path, monkeypatch, [[listing(sid="0", area=60)], [ruin(120_000)], [ruin(100_000, partial=True)]], configure)
    assert seen == {1: "obnova", 2: "obnova"}
    state = State(tmp_path / "s.db")
    assert state.get("t:5")["category"] == "obnova"
    state.close()


def test_daily_prune_of_old_rejected_listings(tmp_path):
    """Odbijeni, nikad javljeni oglasi koji se dugo ne pojavljuju brišu se (s našeg područja
    nakon godine dana, ostali nakon 30 dana); javljeni i oni koji prolaze ostaju."""
    from datetime import timedelta

    from scraper.models import REJECT

    r = Runner(tmp_path / "s.db", tmp_path, send=False)
    state = State(tmp_path / "s.db")
    rows = {"nase_staro": ("Punat", REJECT, 400, None), "nase_novije": ("Punat", REJECT, 100, None),
            "tude_staro": ("Delnice", REJECT, 40, None), "tude_novo": ("Delnice", REJECT, 10, None),
            "javljen": ("Punat", REJECT, 400, "2025-01-01"), "prolazi": ("Punat", PASS, 400, None)}
    for sid, (jls, status, days, notified) in rows.items():
        x = listing(sid=sid)
        state.upsert(x, Decision(status, jls=jls), r.stamp)
        state.conn.execute("UPDATE listings SET last_seen = ?, notified_at = ? WHERE key = ?",
                           ((r.now - timedelta(days=days)).isoformat(timespec="seconds"), notified, x.key))
    state.conn.commit()
    r._prune(state)
    left = {k.split(":")[1] for (k,) in state.conn.execute("SELECT key FROM listings")}
    assert left == {"nase_novije", "tude_novo", "javljen", "prolazi"}
    assert state.conn.execute("SELECT COUNT(*) FROM price_history WHERE key = 't:nase_staro'").fetchone()[0] == 0
    state.conn.execute("UPDATE listings SET last_seen = '2000-01-01' WHERE key = 't:tude_novo'")
    r._prune(state)                                              # jednom dnevno
    assert state.conn.execute("SELECT COUNT(*) FROM listings WHERE key = 't:tude_novo'").fetchone()[0] == 1
    state.close()


def test_detail_captcha_alert_after_three_hours(tmp_path):
    """Captcha na stranicama oglasa dok popis radi: upozorenje nakon 9 pokretanja zaredom
    (jednom), i kad prođe."""
    from types import SimpleNamespace

    r = Runner(tmp_path / "s.db", tmp_path, send=False)
    alerts = []
    r._alert = lambda subject, text: alerts.append(subject) or True
    state = State(tmp_path / "s.db")
    src = SimpleNamespace(name="njuskalo", label="Njuškalo", detail_blocked=True, detail_ok=False,
                          captcha_until="2026-10-08T12:00:00+00:00")
    for _ in range(10):
        r._detail_health(state, src)
    assert alerts == ["Scraper: Njuškalo traži captchu na stranicama oglasa"]
    assert state.meta_get("stanka:njuskalo") == "2026-10-08T12:00:00+00:00"     # stanka ne ovisi o odgođenima
    src.detail_blocked = False
    r._detail_health(state, src)                    # nijedna stranica oglasa otvorena: ništa ne dokazuje
    assert len(alerts) == 1
    src.detail_ok = True
    r._detail_health(state, src)
    r._detail_health(state, src)
    assert alerts[1:] == ["Scraper: Njuškalo – stranice oglasa ponovno rade"]
    state.close()


def test_weekly_labels_redmi_health_rows(tmp_path):
    """Stanje izvora u tjednom izvještaju: retci s Redmija imaju oznaku uređaja."""
    redmi = State(tmp_path / "redmi.db")
    redmi.health_fail("telegram", "Unauthorized")
    redmi.close()
    r = Runner(tmp_path / "s.db", tmp_path, send=False, redmi_db=tmp_path / "redmi.db")
    r._plan_decisions = lambda: None
    bodies = []
    r._email = lambda subject, text, body=None, **k: bodies.append(body)
    r.weekly(record=False)
    assert "<li>Redmi – " in bodies[0] and "Unauthorized" in bodies[0]
