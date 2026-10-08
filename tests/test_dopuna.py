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


def _runs(tmp_path, monkeypatch, batches):
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
    tg = Tg()
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
    # Prvi oglas samo u datoteci s popisom, ili je i sam danas odbijen: bez dopune.
    for mark, status in (("zbirno:t1", PASS), ("t1", REJECT)):
        r._supplements = []
        seen = dedupe.Seen(r.locator)
        seen.add({**dedupe.row(first, Decision(PASS, jls="Omišalj")), "notified_at": mark, "status": status})
        r._rejected_copy(state, seen, pricier, Decision(REJECT, ["nije građevinsko (Poljoprivredno)"], jls="Omišalj"))
        assert r._supplements == []
    state.close()


def test_copy_of_listing_from_overflow_file_gets_no_supplement(tmp_path, monkeypatch):
    """Previše novih oglasa odjednom → popis u datoteci; kopija takvog oglasa ne šalje dopunu
    (nema poruke na koju bi odgovorila)."""
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
