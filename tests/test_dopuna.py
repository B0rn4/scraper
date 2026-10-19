"""Dopuna s preciznijeg portala: isti oglas s drugog portala donosi samo ono što je novo."""

import json

from scraper import dedupe, dopuna
from scraper.db import State
from scraper.ispu import PointInfo
from scraper.models import HOUSE, LAND, PASS, REJECT, WARN, Decision, Listing
from scraper.runner import Runner


def land(source, sid, **kw):
    x = Listing(source=source, source_id=sid, url=f"https://{source}/{sid}", title="Građevinsko zemljište Njivice",
                kind=LAND, subtype="Građevinsko zemljište", price=120_000, area=650, county="Primorsko-goranska",
                municipality="Omišalj", settlement="Njivice")
    for key, value in kw.items():
        if key in ("lat", "lon", "priblizna_lokacija", "krug_m", "godina_izgradnje", "vlasnicki_list"):
            x.extra[key] = value
        else:
            setattr(x, key, value)
    return x


class FakeIspu:
    def parcel(self, ko, kc, names=None):
        return None

    def point(self, lat, lon):
        return PointInfo(gp="naselja", use="(GP) IZGRAĐENI DIO GRAĐEVINSKOG PODRUČJA NASELJA",
                         block="NJIVICE - GRAĐEVINSKO", land_values=[150.0, 200.0])

    def gp_share(self, lat, lon, radius):
        return PointInfo(block="NJIVICE - GRAĐEVINSKO"), {"naselja": 0.6}


class Tg:
    chat_id = "42"

    def __init__(self):
        self.listings, self.replies, self.next = [], [], 100

    def send_listing(self, x, d, headline=""):
        self.next += 1
        self.listings.append(x.key)
        return [self.next]

    def send_reply(self, text, reply_to, url, silent=True):
        self.next += 1
        self.replies.append({"text": text, "reply_to": reply_to, "url": url, "silent": silent})
        return self.next


def _runs(tmp_path, monkeypatch, batches, tg=None):
    """Pokretanja s lažnim izvorom (svaki oglas nosi svoj portal) i lažnim Telegramom."""
    import scraper.runner as runner_mod

    class Src:
        name, label, daily = "fake", "fake", False

        def __init__(self, *a, **k):
            pass

        def fetch(self, mode, known_ids):
            return batches.pop(0)

        def search_links(self):
            return []

    monkeypatch.setitem(runner_mod.ALL, "fake", Src)
    tg = tg or Tg()
    for _ in range(len(batches)):
        r = Runner(tmp_path / "s.db", tmp_path / "out", send=False)
        r.cfg["izvori"] = {"fake": True}
        r._send_report = lambda *a, **k: None
        r._banks = r._tenders = r._ppv_reminder = lambda *a, **k: None
        r._ispu = FakeIspu()
        r.telegram = tg
        r.run(force=True)
    return tg


def test_copy_with_precise_location_sends_only_what_is_new(tmp_path, monkeypatch):
    """oglasnik (bez lokacije) → poruka; vender (točna oznaka) → dopuna kao odgovor na nju, samo
    🗺 i PPV na lokaciji; index s približnom oznakom ne donosi ništa novo; burza „poljoprivredno” →
    dopuna s ⚠ (nije tiha)."""
    first = land("oglasnik", "1")
    precise = land("vender", "2", lat=45.16, lon=14.55, priblizna_lokacija=False)
    approx = land("index_oglasi", "3", lat=45.16, lon=14.55, priblizna_lokacija=True)
    farm = land("burza", "4", subtype="Poljoprivredno zemljište", title="Zemljište Njivice")
    tg = _runs(tmp_path, monkeypatch, [[land("oglasnik", "0", area=100)], [first], [precise], [approx, farm]])
    assert tg.listings == ["oglasnik:1"]
    assert len(tg.replies) == 2
    reply = tg.replies[0]
    assert reply["reply_to"] == 101 and reply["url"] == "https://vender/2" and reply["silent"]
    lines = reply["text"].splitlines()
    assert lines[0] == "➕ <b>Dopuna s vender.hr</b>"
    assert lines[1].startswith("🗺 U građevinskom području naselja (izgrađeni dio) – ISPU, prema oznaci na karti")
    assert lines[2].startswith("🏛 PPV (na lokaciji, blok Njivice - Građevinsko)")
    assert not any(x.startswith(("📍", "📏", "💶")) for x in lines)       # bez ponavljanja prve poruke
    warn = tg.replies[1]
    assert warn["reply_to"] == 101 and not warn["silent"]
    assert "⚠ prema ovom oglasu ne odgovara kriterijima: nije građevinsko (Poljoprivredno zemljište)" in warn["text"]
    state = State(tmp_path / "s.db")
    assert state.get("vender:2")["notified_at"] == "dup:oglasnik:1"
    assert state.message_key(102) == "oglasnik:1"        # 👎 na dopunu = na prvi oglas
    assert json.loads(state.meta_get("dopune")) == []
    state.close()


def test_unsent_supplement_waits_and_is_retried(tmp_path, monkeypatch):
    first, precise = land("oglasnik", "1"), land("vender", "2", lat=45.16, lon=14.55, priblizna_lokacija=False)

    class Down(Tg):
        def send_reply(self, *a, **k):
            raise RuntimeError("Telegram sendMessage: 502 Bad Gateway")

    import scraper.runner as runner_mod
    batches = [[land("oglasnik", "0", area=100)], [first], [precise], [precise]]

    class Src:
        name, label, daily = "fake", "fake", False

        def __init__(self, *a, **k):
            pass

        def fetch(self, mode, known_ids):
            return batches.pop(0)

        def search_links(self):
            return []

    monkeypatch.setitem(runner_mod.ALL, "fake", Src)
    tg, down = Tg(), Down()
    for i in range(4):
        r = Runner(tmp_path / "s.db", tmp_path / "out", send=False)
        r.cfg["izvori"] = {"fake": True}
        r._send_report = lambda *a, **k: None
        r._banks = r._tenders = r._ppv_reminder = lambda *a, **k: None
        r._ispu = FakeIspu()
        r.telegram = down if i == 2 else tg
        r.run(force=True)
    assert len(tg.replies) == 1 and tg.replies[0]["reply_to"] == 101


def test_news_compares_with_what_message_said():
    d = Decision(WARN, warnings=["suvlasništvo: „Vlasnici su dvoje braće, suvlasništvo 1/2.”"], jls="Punat")
    house = Listing("index_oglasi", "1", "https://i/1", "Kuća Punat", HOUSE, price=280_000, area=120,
                    municipality="Punat", settlement="Punat")
    house.extra.update({"gp": "🗺 Građevinsko područje: nije provjereno – oglas nema točnu lokaciju ni broj čestice",
                        "parking_redak": "🚗 parking: nema podataka (oglas bez opisa)"})
    old = dopuna.snapshot(house, d)
    assert old["lokacija"] == 0 and old["gp"] == [] and old["parking"] == ""

    copy = Listing("njuskalo", "2", "https://n/2", "Kuća Punat", HOUSE, subtype="Samostojeća kuća",
                   price=280_000, area=120, plot_area=400, municipality="Punat", settlement="Punat")
    copy.extra.update({"godina_izgradnje": 1985, "vlasnicki_list": True, "lokacija_rang": 2,
                       "gp": "🗺 U građevinskom području naselja – ISPU, prema oznaci na karti oglasa",
                       "parking_redak": "🚗 garaža (iz opisa)"})
    d2 = Decision(WARN, warnings=["suvlasništvo: „Suvlasnici 1/1, druga rečenica.”",
                                 "nasljednici / ostavina: „Ostavinski postupak u tijeku.”",
                                 "površina nije navedena"], jls="Punat")
    lines = dopuna.news(old, dopuna.snapshot(copy, d2), copy, d2)
    assert lines == [
        "🗺 U građevinskom području naselja – ISPU, prema oznaci na karti oglasa",
        "🏗 vrsta: Samostojeća kuća · okućnica 400 m² · izgrađena 1985 · vlasnički list ✔",
        "🚗 garaža (iz opisa)",
        "⚠ nasljednici / ostavina: „Ostavinski postupak u tijeku.”"]
    # Nakon dopune: isti podaci s trećeg portala nisu novost.
    merged = dopuna.merge(old, dopuna.snapshot(copy, d2))
    assert dopuna.news(merged, dopuna.snapshot(copy, d2), copy, d2) == []


def test_legacy_message_knows_only_portal_location():
    """Poruka poslana prije pamćenja snimke: s portala bez lokacije nova lokacija je novost, ostalo
    se ne uspoređuje (ne zna se što je poruka rekla)."""
    old = dopuna.legacy({"source": "oglasnik"})
    copy = land("vender", "2")
    copy.extra.update({"lokacija_rang": 2, "gp": "🗺 NIJE u građevinskom području – ISPU, prema oznaci na karti oglasa",
                       "godina_izgradnje": 1990})
    d = Decision(WARN, warnings=["vrsta zemljišta nije navedena", "prema ISPU-u nije u građevinskom području – provjeri"],
                 jls="Omišalj")
    lines = dopuna.news(old, dopuna.snapshot(copy, d), copy, d, location_warnings=d.warnings[1:])
    assert lines == ["🗺 NIJE u građevinskom području – ISPU, prema oznaci na karti oglasa",
                     "⚠ prema ISPU-u nije u građevinskom području – provjeri"]
    assert dopuna.news(dopuna.legacy({"source": "njuskalo"}), dopuna.snapshot(copy, d), copy, d) == []


def test_seen_file_carries_message_and_snapshot(tmp_path):
    """Redmi zna broj prve poruke i snimku s GitHuba (sažetak viđenih oglasa)."""
    state = State(tmp_path / "s.db")
    x = land("oglasnik", "1")
    state.upsert(x, Decision(PASS, jls="Omišalj"), "t1")
    state.mark_notified(x.key, x.price, "t1")
    state.remember_message(77, x.key, "t1")
    state.remember_message(78, x.key, "t1")
    state.set_info(x.key, {"lokacija": 0}, "t1")
    copy = land("vender", "2")
    state.upsert(copy, Decision(PASS, jls="Omišalj"), "t2")
    state.mark_notified(copy.key, copy.price, f"dup:{x.key}")
    dedupe.export(state, tmp_path / "seen.json.gz")
    state.close()
    seen = dedupe.Seen()
    seen.add_file(tmp_path / "seen.json.gz")
    root = seen.root("vender:2")
    assert root["key"] == "oglasnik:1" and root["poruka"] == 77 and dopuna.load(root) == {"lokacija": 0}
    assert [r["key"] for r in seen.family("oglasnik:1")] == ["vender:2"]


def test_rejected_copy_only_for_reasons_beyond_price_and_area(tmp_path):
    r = Runner(tmp_path / "s.db", tmp_path, send=False)
    state = State(tmp_path / "s.db")
    seen = dedupe.Seen(r.locator)
    first = land("oglasnik", "1")
    seen.add({**dedupe.row(first, Decision(PASS, jls="Omišalj")), "notified_at": "t1"})
    pricier = land("burza", "2")
    r._rejected_copy(state, seen, pricier, Decision(REJECT, ["cijena 121.000 € > 120.000 €"], jls="Omišalj"))
    assert r._supplements == []
    # Grad/općina izvan popisa: isti je i za prvi oglas – promjena pravila, ne nov podatak.
    r._rejected_copy(state, seen, pricier, Decision(REJECT, ["lokacija nije na popisu (Omišalj)"], jls="Omišalj"))
    assert r._supplements == []
    r._rejected_copy(state, seen, pricier, Decision(REJECT, ["nije građevinsko (Poljoprivredno)"], jls="Omišalj"))
    assert [i["za"] for i in r._supplements] == ["oglasnik:1"] and r._supplements[0]["odbijen"]
    # Prvi oglas i sam danas odbijen: bez dopune. Samo u datoteci s popisom: u red (napomena, 13. 10.).
    for mark, status, queued in (("t1", REJECT, []), ("zbirno:t1", PASS, ["oglasnik:1"])):
        r._supplements = []
        seen = dedupe.Seen(r.locator)
        seen.add({**dedupe.row(first, Decision(PASS, jls="Omišalj")), "notified_at": mark, "status": status})
        r._rejected_copy(state, seen, pricier, Decision(REJECT, ["nije građevinsko (Poljoprivredno)"], jls="Omišalj"))
        assert [i["za"] for i in r._supplements] == queued
    state.close()


def test_copy_of_listing_from_overflow_file_is_noted_not_sent(tmp_path, monkeypatch):
    """Previše novih oglasa odjednom → popis u datoteci; kopija takvog oglasa ne šalje dopunu
    (nema poruke na koju bi odgovorila), nego novo pamti uz prvi oglas (odluka 13. 10.)."""
    first = land("oglasnik", "1")
    precise = land("vender", "2", lat=45.16, lon=14.55, priblizna_lokacija=False)
    import scraper.runner as runner_mod
    monkeypatch.setattr(runner_mod.Runner, "_send_report", lambda *a, **k: True)
    batches = [[land("oglasnik", "0", area=100)], [first], [precise]]

    class Src:
        name, label, daily = "fake", "fake", False

        def __init__(self, *a, **k):
            pass

        def fetch(self, mode, known_ids):
            return batches.pop(0)

        def search_links(self):
            return []

    monkeypatch.setitem(runner_mod.ALL, "fake", Src)
    tg = Tg()
    for i in range(3):
        r = Runner(tmp_path / "s.db", tmp_path / "out", send=False)
        r.cfg["izvori"] = {"fake": True}
        r.cfg["obavijesti"]["max_poruka_po_pokretanju"] = 0       # svaka obavijest ide u datoteku
        r._banks = r._tenders = r._ppv_reminder = lambda *a, **k: None
        r._ispu = FakeIspu()
        r.telegram = tg
        r.run(force=True)
    state = State(tmp_path / "s.db")
    assert state.get("oglasnik:1")["notified_at"].startswith("zbirno:")
    assert state.get("vender:2")["notified_at"] == "dup:oglasnik:1"
    assert tg.replies == [] and not json.loads(state.meta_get("dopune") or "[]")
    [note] = state.notes()["oglasnik:1"]
    assert note["kopija"] == "vender:2" and note["url"] == "https://vender/2" and not note["ne_odgovara"]
    assert note["retci"][0].startswith("🗺 U građevinskom području naselja") and note["retci"][1].startswith("🏛 PPV")
    state.close()


def test_listing_from_initial_list_gets_notes_not_messages(tmp_path, monkeypatch):
    """Oglas iz početnog popisa: kopija s drugog portala koja prema svojim podacima ne odgovara
    ne šalje ⚠ dopunu, nego je napomena uz prvi oglas; ista ⚠ s trećeg portala se ne ponavlja,
    a nova se doda. Završni pregled napomene prikazuje uz oglas (report.entry)."""
    from scraper import report

    first = land("oglasnik", "1")
    farm = land("burza", "4", subtype="Poljoprivredno zemljište", title="Zemljište Njivice")
    farm2 = land("index_oglasi", "5", subtype="", title="Poljoprivredno zemljište Njivice")
    share = land("nekretnine_hr", "6", description="Građevinsko zemljište. Prodaje se suvlasnički dio od 1/2 zemljišta.")
    tg = _runs(tmp_path, monkeypatch, [[first], [farm], [farm2, share]])
    assert tg.listings == [] and tg.replies == []
    state = State(tmp_path / "s.db")
    assert state.get("oglasnik:1")["notified_at"].startswith("zbirno:")     # početni popis
    notes = state.notes()["oglasnik:1"]
    assert [(n["kopija"], n["ne_odgovara"]) for n in notes] == [("burza:4", True), ("nekretnine_hr:6", True)]
    assert notes[0]["retci"] == ["⚠ prema ovom oglasu ne odgovara kriterijima: nije građevinsko (Poljoprivredno zemljište)"]
    assert notes[1]["retci"][0].startswith("⚠ prema ovom oglasu ne odgovara kriterijima: prodaje se suvlasnički dio")
    assert state.get("burza:4")["notified_at"] == "dup:oglasnik:1"
    assert state.get("index_oglasi:5")["notified_at"] is None          # ništa novo: bez napomene i oznake
    entry = report.entry(first, Decision(PASS, jls="Omišalj"), notes)
    assert entry["n"][0] == {"s": "burza.com.hr", "u": "https://burza/4", "x": True, "l": notes[0]["retci"]}
    state.close()


def old(source, sid, **kw):
    """Stari oglas (agencija ga je osvježila): zabilježi se tiho, bez poruke."""
    x = land(source, sid, **kw)
    x.extra["stari_oglas"] = True
    return x


def test_copy_of_silently_recorded_old_listing_is_not_new(tmp_path, monkeypatch):
    """Odluka korisnika 19. 10.: kopija tiho zabilježenog starog oglasa s drugog portala je i
    dalje stari oglas – ne stiže; novo s nje (bolja lokacija, "ne odgovara") je napomena za
    završni pregled, kao kod oglasa iz početnog popisa."""
    precise = land("vender", "2", lat=45.16, lon=14.55, priblizna_lokacija=False)
    farm = land("burza", "4", subtype="Poljoprivredno zemljište", title="Zemljište Njivice")
    tg = _runs(tmp_path, monkeypatch, [[land("oglasnik", "0", area=100)], [old("oglasnik", "1")], [precise, farm]])
    assert tg.listings == [] and tg.replies == []
    state = State(tmp_path / "s.db")
    assert state.get("oglasnik:1")["notified_at"].startswith("tiho:")
    assert state.get("vender:2")["notified_at"] == "dup:oglasnik:1"
    assert state.get("burza:4")["notified_at"] == "dup:oglasnik:1"
    notes = {n["kopija"]: n for n in state.notes()["oglasnik:1"]}
    assert notes["vender:2"]["retci"][0].startswith("🗺 U građevinskom području naselja") and not notes["vender:2"]["ne_odgovara"]
    assert notes["burza:4"]["retci"] == ["⚠ prema ovom oglasu ne odgovara kriterijima: nije građevinsko (Poljoprivredno zemljište)"]
    state.close()


def test_cheaper_copy_of_old_listing_has_button_for_older_one(tmp_path, monkeypatch):
    """Jeftinija kopija starog oglasa stiže (📉 Već viđen … sad jeftiniji), s gumbom za stariji
    oglas: prvi nije imao svoju poruku (odluka korisnika 19. 10.)."""
    from scraper.notify import listing_markup

    class Recording(Tg):
        def send_listing(self, x, d, headline=""):
            self.sent = getattr(self, "sent", []) + [(x, headline)]
            return super().send_listing(x, d, headline)

    cheaper = land("nekretnine_hr", "6", price=110_000)
    tg = _runs(tmp_path, monkeypatch, [[land("oglasnik", "0", area=100)], [old("index_oglasi", "1")], [cheaper]],
               Recording())
    [(x, headline)] = tg.sent
    assert x.key == "nekretnine_hr:6" and headline == "📉 Već viđen na index.hr/oglasi za 120.000 € – sad jeftiniji"
    assert x.extra["stariji_oglas"] == {"url": "https://index_oglasi/1", "izvor": "index.hr/oglasi"}
    rows = json.loads(listing_markup(x))["inline_keyboard"]
    assert rows == [[{"text": "Otvori oglas", "url": "https://nekretnine_hr/6"}],
                    [{"text": "Stariji oglas (index.hr/oglasi)", "url": "https://index_oglasi/1"}]]


def test_price_drop_of_sent_listing_is_not_hidden_by_silent_twin(tmp_path, monkeypatch):
    """Poslan oglas pojeftini na cijenu tiho zabilježenog starog oglasa s drugog portala: sniženje
    stiže – cijenu tiho zabilježenog korisnik nije vidio."""
    tg = _runs(tmp_path, monkeypatch, [[land("oglasnik", "0", area=100)], [land("oglasnik", "1", price=130_000)],
                                       [old("index_oglasi", "3")], [land("oglasnik", "1", price=120_000)]])
    assert tg.listings == ["oglasnik:1", "oglasnik:1"]
    state = State(tmp_path / "s.db")
    assert state.get("oglasnik:1")["notified_price"] == 120_000
    state.close()


def test_copy_prefers_twin_with_own_message_over_silent_one(tmp_path, monkeypatch):
    """Isti oglas poslan porukom i (kasnije) tiho zabilježen kao star na drugom portalu: treća
    kopija je "isti kao" poslani i dopuna je odgovor na njegovu poruku, a ne napomena."""
    precise = land("vender", "2", lat=45.16, lon=14.55, priblizna_lokacija=False)
    tg = _runs(tmp_path, monkeypatch, [[land("oglasnik", "0", area=100)], [land("oglasnik", "1")],
                                       [old("index_oglasi", "3")], [precise]])
    assert tg.listings == ["oglasnik:1"]
    assert [r["reply_to"] for r in tg.replies] == [101] and tg.replies[0]["url"] == "https://vender/2"
    state = State(tmp_path / "s.db")
    assert state.get("index_oglasi:3")["notified_at"].startswith("tiho:")
    assert state.get("vender:2")["notified_at"] == "dup:oglasnik:1"
    assert state.notes() == {}
    state.close()


def test_send_reply_is_reply_with_button_and_quiet(monkeypatch):
    from scraper import notify
    from scraper.notify import Telegram

    calls = []

    class Resp:
        status_code, headers, text = 200, {"content-type": "application/json"}, ""

        def json(self):
            return {"ok": True, "result": {"message_id": 9}}

    monkeypatch.setattr(notify.requests, "post", lambda url, data=None, **k: (calls.append(data), Resp())[1])
    monkeypatch.setattr(notify.time, "sleep", lambda s: None)
    assert Telegram("t", "1").send_reply("➕ <b>Dopuna s vender.hr</b>", 101, "https://v/ž 2", silent=True) == 9
    data = calls[0]
    assert json.loads(data["reply_parameters"]) == {"message_id": 101, "allow_sending_without_reply": True}
    assert data["disable_notification"] == "true"
    assert json.loads(data["reply_markup"])["inline_keyboard"][0][0] == {"text": "Otvori oglas", "url": "https://v/%C5%BE%202"}
    Telegram("t", "1").send_reply("x", None, "https://v/2", silent=False)
    assert "reply_parameters" not in calls[1] and calls[1]["disable_notification"] == "false"


def test_rejected_copy_warning_is_not_repeated_by_other_device(tmp_path, monkeypatch):
    """Ista ⚠ ("ne odgovara") s drugog portala ili s Redmija ne stiže dvaput (9. 10.: Rukavac je
    stigao s index.hr i s Njuškala): odbijena kopija s dopunom ulazi među kopije prvog oglasa i
    pamti razlog; drugi uređaj to vidi u sažetku viđenih oglasa."""
    first = land("oglasnik", "1")
    farm = land("burza", "4", subtype="Poljoprivredno zemljište", title="Zemljište Njivice")
    farm2 = land("index_oglasi", "5", subtype="Poljoprivredno zemljište", title="Zemljište Njivice")
    tg = _runs(tmp_path, monkeypatch, [[land("oglasnik", "0", area=100)], [first], [farm], [farm2]])
    assert len(tg.replies) == 1 and "nije građevinsko" in tg.replies[0]["text"]
    state = State(tmp_path / "s.db")
    assert state.get("burza:4")["notified_at"] == "dup:oglasnik:1"
    dedupe.export(state, tmp_path / "seen.json.gz")
    state.close()
    seen = dedupe.Seen()
    seen.add_file(tmp_path / "seen.json.gz")           # drugi uređaj
    family = seen.family("oglasnik:1")
    assert [r["key"] for r in family] == ["burza:4"] and dopuna.load(family[0])["razlozi"]


def test_same_rejection_in_other_words_is_not_repeated(tmp_path, monkeypatch):
    """13. runda F-D: "nije građevinsko (Poljoprivredno zemljište)" i "(naslov)" su isti razlog."""
    first = land("oglasnik", "1")
    farm = land("burza", "4", subtype="Poljoprivredno zemljište", title="Zemljište Njivice")
    farm2 = land("index_oglasi", "5", subtype="", title="Poljoprivredno zemljište Njivice")
    tg = _runs(tmp_path, monkeypatch, [[land("oglasnik", "0", area=100)], [first], [farm], [farm2]])
    assert len(tg.replies) == 1 and "nije građevinsko (Poljoprivredno zemljište)" in tg.replies[0]["text"]
    assert dopuna.warning_key("ruševina: „Kuća je ruševna.”") == dopuna.warning_key("ruševina: „Ruševina Punat.”")


def test_supplement_waits_without_telegram_and_keeps_its_button_after_dislike(tmp_path, monkeypatch):
    """F-J: bez Telegrama dopuna čeka (kao obavijest). F-K: nakon 👎 gumb dopune ostaje na novom portalu."""
    import scraper.runner as runner_mod
    first, precise = land("oglasnik", "1"), land("vender", "2", lat=45.16, lon=14.55, priblizna_lokacija=False)
    batches = [[land("oglasnik", "0", area=100)], [first], [precise], []]

    class Src:
        name, label, daily = "fake", "fake", False

        def __init__(self, *a, **k):
            pass

        def fetch(self, mode, known_ids):
            return batches.pop(0) or [land("oglasnik", "0", area=100)]

        def search_links(self):
            return []

    monkeypatch.setitem(runner_mod.ALL, "fake", Src)
    tg = Tg()
    for i in range(4):
        r = Runner(tmp_path / "s.db", tmp_path / "out", send=False)
        r.cfg["izvori"] = {"fake": True}
        r._send_report = lambda *a, **k: None
        r._banks = r._tenders = r._ppv_reminder = lambda *a, **k: None
        r._ispu = FakeIspu()
        r.telegram = None if i == 2 else tg
        r.run(force=True)
    assert len(tg.replies) == 1 and tg.replies[0]["url"] == "https://vender/2"
    state = State(tmp_path / "s.db")
    mid = max(m for (m,) in state.conn.execute("SELECT message_id FROM messages"))
    assert state.message_key(mid) == "oglasnik:1" and state.message_url(mid) == "https://vender/2"
    state.close()


def test_queued_listing_description_has_no_contacts(tmp_path):
    """F-H: red čekanja je u javnoj bazi stanja – opis bez bloka s kontaktom, telefona i e-adresa."""
    from scraper.runner import _stored
    x = land("vender", "2", description="Građevinsko zemljište 650 m2, k.č. 1234/5 k.o. Njivice. Pogled na more i "
                                         "mirna lokacija.\nKontakt: Ivan Horvat, 091.503.2253, ivan.horvat@gmail.com")
    text = json.dumps(_stored(x), ensure_ascii=False)
    assert "Horvat" not in text and "2253" not in text and "gmail" not in text and "k.č. 1234/5" in text


def test_permits_in_message_and_supplement():
    """Dozvole s portala: 🏗 redak poruke; dopuna javlja samo dozvolu koje prva poruka nije imala."""
    from scraper.notify import format_listing

    d = Decision(PASS, jls="Punat")
    first = Listing("index_oglasi", "1", "https://i/1", "Kuća Punat", HOUSE, price=280_000, area=120,
                    municipality="Punat", settlement="Punat")
    first.extra.update({"vlasnicki_list": True, "dozvole": ["građevinska dozvola"]})
    assert "🏗 vlasnički list ✔ · građevinska dozvola ✔" in format_listing(first, d)
    copy = Listing("oglasnik", "2", "https://o/2", "Kuća Punat", HOUSE, price=280_000, area=120,
                   municipality="Punat", settlement="Punat")
    copy.extra.update({"vlasnicki_list": True, "dozvole": ["građevinska dozvola", "uporabna dozvola"]})
    lines = dopuna.news(dopuna.snapshot(first, d), dopuna.snapshot(copy, d), copy, d)
    assert lines == ["🏗 uporabna dozvola ✔"]


def test_land_utilities_in_supplement():
    """Dopuna javlja priključke koje prva poruka nije imala (samo zemljišta)."""
    d = Decision(PASS, jls="Omišalj")
    first = Listing("oglasnik", "1", "https://o/1", "Zemljište Njivice", LAND, price=150_000, area=800)
    first.extra["prikljucci"] = ["voda"]
    copy = Listing("vender", "2", "https://v/2", "Zemljište Njivice", LAND, price=150_000, area=800)
    copy.extra["prikljucci"] = ["struja", "voda", "asfaltni put"]
    lines = dopuna.news(dopuna.snapshot(first, d), dopuna.snapshot(copy, d), copy, d)
    assert lines == ["🔌 priključci: struja ✔ · asfaltni put ✔"]


def test_earlier_rejected_copies_become_notes_once(tmp_path):
    """Jednokratno: odbijene kopije oglasa iz popisa zabilježene prije napomena – samo razlozi
    odbijanja (u bazi su zajedno s upozorenjima), bez ponavljanja istog razloga; ne kopije iz
    početnog popisa svog portala ni kopije oglasa s vlastitom porukom."""
    r = Runner(tmp_path / "s.db", tmp_path, send=False)
    state = State(tmp_path / "s.db")
    for source, at in (("oglasnik", "2026-10-04T16:58:25+02:00"), ("burza", "2026-10-06T15:25:50+02:00"),
                       ("index_oglasi", "2026-10-04T16:58:25+02:00")):
        state.meta_set(f"baseline:{source}", at)
    first, sent = land("oglasnik", "1"), land("oglasnik", "2", area=900, price=150_000)
    for x, mark in ((first, "zbirno:2026-10-04T16:58:25+02:00"), (sent, "2026-10-09T10:00:00+02:00")):
        state.upsert(x, Decision(PASS, jls="Omišalj"), "2026-10-04T16:58:25+02:00")
        state.mark_notified(x.key, x.price, mark)
    farm = Decision(REJECT, ["nije građevinsko (Poljoprivredno zemljište)", "cijena 121.000 € > 120.000 €"],
                    ["vrsta zemljišta nije navedena", "Njivice: daleko od Rijeke"], jls="Omišalj")
    copies = [(land("burza", "4"), "2026-10-08T09:00:00+02:00"),          # → napomena
              (land("index_oglasi", "5"), "2026-10-09T09:00:00+02:00"),   # isti razlog: ništa
              (land("burza", "6"), "2026-10-06T15:25:50+02:00"),          # početni popis burze
              (land("index_oglasi", "7", area=900, price=150_000), "2026-10-10T09:00:00+02:00")]  # poslan oglas
    for x, at in copies:
        state.upsert(x, farm, at)
    seen = dedupe.Seen(r.locator)
    seen.add_state(state)
    r._repair_list_notes(state, seen)
    assert state.notes() == {"oglasnik:1": [{
        "kopija": "burza:4", "izvor": "burza", "url": "https://burza/4", "ne_odgovara": True, "at": "2026-10-08T09:00:00+02:00",
        "retci": ["⚠ prema ovom oglasu ne odgovara kriterijima: nije građevinsko (Poljoprivredno zemljište)"]}]}
    assert state.get("burza:4")["notified_at"] == "dup:oglasnik:1"
    assert state.duplicates_since("2000") == []        # tjedni izvještaj: odbijena, ne "preskočena"
    assert [state.get(k)["notified_at"] for k in ("index_oglasi:5", "burza:6", "index_oglasi:7")] == [None] * 3
    assert state.meta_get("popravak:napomene_popisa")
    state.close()


def test_earlier_rejected_copies_of_silent_old_listing_become_notes_once(tmp_path):
    """Jednokratno (odluka 19. 10.): isto za tiho zabilježene stare oglase – a samo za njih
    (napomene za oglase iz popisa već su popunjene 13. 10.)."""
    r = Runner(tmp_path / "s.db", tmp_path, send=False)
    state = State(tmp_path / "s.db")
    for source in ("oglasnik", "burza", "index_oglasi"):
        state.meta_set(f"baseline:{source}", "2026-10-04T16:58:25+02:00")
    silent, listed = land("oglasnik", "1"), land("oglasnik", "2", area=900, price=150_000)
    for x, mark in ((silent, "tiho:2026-10-07T10:00:00+02:00"), (listed, "zbirno:2026-10-04T16:58:25+02:00")):
        state.upsert(x, Decision(PASS, jls="Omišalj"), "2026-10-04T16:58:25+02:00")
        state.mark_notified(x.key, x.price, mark)
    farm = Decision(REJECT, ["nije građevinsko (Poljoprivredno zemljište)"], jls="Omišalj")
    for x in (land("burza", "4"), land("index_oglasi", "7", area=900, price=150_000)):
        state.upsert(x, farm, "2026-10-08T09:00:00+02:00")
    seen = dedupe.Seen(r.locator)
    seen.add_state(state)
    r._repair_list_notes(state, seen, silent=True)
    assert list(state.notes()) == ["oglasnik:1"] and state.notes()["oglasnik:1"][0]["kopija"] == "burza:4"
    assert state.get("burza:4")["notified_at"] == "dup:oglasnik:1"
    assert state.get("index_oglasi:7")["notified_at"] is None      # kopija oglasa iz popisa: već 13. 10.
    assert state.meta_get("popravak:napomene_tiho") and not state.meta_get("popravak:napomene_popisa")
    state.close()
