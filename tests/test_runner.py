"""Logika obavijesti (nov oglas, snižena cijena, početni popis) bez mreže."""

import json

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
    assert buttons[0]["url"] == "https://x" and buttons[1]["callback_data"] == "nz:t:7"

    class Tg:
        chat_id = "42"

        def __init__(self):
            self.edited, self.sent, self.confirmed = [], [], set()
            self.updates = [
                {"update_id": 10, "callback_query": {"id": "q1", "data": "nz:t:7",
                 "message": {"message_id": 5, "chat": {"id": 42},
                             "reply_markup": json.loads(listing_markup(x))}}},
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
    undo = json.loads(muted_markup({}, "t:7"))["inline_keyboard"][0][0]
    assert "poništenje" in undo["text"] and undo["callback_data"] == "pz:t:7"
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
    assert tg.edited[-1][1]["inline_keyboard"][0][-1]["callback_data"] == "nz:t:7"
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

    alerts = []
    r._alert = lambda subject, text: alerts.append(subject) or True
    state.meta_set("tjedni:neposlan", (r.now - timedelta(days=3)).isoformat())
    r._retry_weekly(state)
    assert alerts == ["Scraper: tjedni izvještaj nije poslan"] and not state.meta_get("tjedni:neposlan")
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


def test_button_test_answers_probe_and_records_mute(tmp_path, monkeypatch):
    """Proba gumba: probni gumb odmah dobije odgovor, "Ne zanima me" se zapiše, a 409
    (isti bot čita još netko) se izbroji."""
    import scraper.runner as runner_mod
    from scraper.notify import PROBE, listing_markup

    monkeypatch.setattr(runner_mod.time, "sleep", lambda s: None)
    x = listing(sid="7")
    batches = [RuntimeError("Telegram getUpdates: 409 Conflict: terminated by other getUpdates request"),
               [{"update_id": 5, "callback_query": {"id": "q1", "data": PROBE, "message": {"message_id": 1, "chat": {"id": 42}}}},
                {"update_id": 6, "callback_query": {"id": "q2", "data": "nz:t:7", "message": {
                    "message_id": 2, "chat": {"id": 42}, "reply_markup": json.loads(listing_markup(x))}}}]]

    class Tg:
        chat_id = "42"
        answers, probes = [], []

        def send_probe(self, minutes):
            self.probes.append(minutes)

        def get_updates(self, offset, wait=0):
            if offset or not batches:
                return []
            item = batches.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        def answer_callback(self, qid, text):
            self.answers.append((qid, text))

        def edit_markup(self, *a):
            pass

    r = Runner(tmp_path / "s.db", tmp_path, send=False)
    r.telegram = Tg()
    r.button_test(minutes=0.002)
    state = State(tmp_path / "s.db")
    assert state.muted() == {"t:7"} and state.meta_get("telegram:offset") == "7"
    state.close()
    assert ("q1", "Stiglo! Gumb radi.") in Tg.answers and Tg.probes == [0.002]
    assert "sukoba s drugim čitačem (409) 1" in r.log_lines[-1]
