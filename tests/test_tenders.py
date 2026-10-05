import json
from datetime import date, timedelta

from scraper import tenders
from scraper.locations import Locator
from scraper.tenders import Reader, Tender, details, format_tender, relevant

TODAY = date.today()


class Resp:
    def __init__(self, text, url=""):
        self.text, self.url = text, url

    def json(self):
        return json.loads(self.text)


class FakeHttp:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, url, params=None, **kwargs):
        self.calls.append((url, params))
        for key, body in self.routes.items():
            if key in url:
                return Resp(body, url)
        raise RuntimeError(f"nema odgovora za {url}")


def test_relevant_titles():
    assert relevant("NATJEČAJ ZA PRODAJU ZEMLJIŠTA k.č. 788/2 k.o. VRBNIK")
    assert relevant("Natječaj za prodaju nekretnine – Mate Balote")
    assert relevant("Natječaj za prodaju građevinskog zemljišta u vlasništvu Grada Crikvenice")
    for title in ("Javni natječaj za prodaju rabljenog vozila", "Javni natječaj za prodaju stanova Grada Rijeke",
                  "Natječaj za zakup poslovnog prostora", "Odluka o izboru najpovoljnijeg ponuditelja za prodaju zemljišta",
                  "Javni poziv za savjetovanje o kupoprodaji poslovnog prostora", "Javni natječaj za prijam u službu"):
        assert not relevant(title), title


def test_details():
    info = details("Predmet prodaje je 79/100 dijela nekretnine k.č. 758 k.o. Kostrena-Barbara, površine 650 m2. "
                   "Početna cijena iznosi 120.000,00 EUR. Rok za podnošenje ponuda je 15. listopada 2026.")
    assert info == {"rok": "2026-10-15", "cijene": [120000.0], "dio": True, "povrsine": [650.0]}


def test_reader_wp_rss_page():
    wp = json.dumps([
        {"date": "2026-09-21T10:00:00", "link": "https://m.hr/prodaja-1", "title": {"rendered": "Natječaj za prodaju nekretnine &#8211; Učiteljska"},
         "content": {"rendered": "<p>Prodaje se k.č. 12/3 k.o. Malinska.</p>"}},
        {"date": "2026-09-20T10:00:00", "link": "https://m.hr/vozilo", "title": {"rendered": "Natječaj za prodaju vozila"}, "content": {"rendered": ""}}])
    rss = ("<rss><channel><item><title>Natječaj za prodaju nekretnine</title><link>https://b.hr/n1</link>"
           "<pubDate>Mon, 21 Sep 2026 08:00:00 +0000</pubDate><description><![CDATA[Opis]]></description></item></channel></rss>")
    page = ('<a href="/natjecaj-zemljiste">NATJEČAJ-prodaja zemljišta u Dobrinju</a><a href="/kultura">Javni poziv za kulturu</a>'
            '<a href="/x.pdf">Natječaj za prodaju nekretnine u Zagrebu</a>')
    http = FakeHttp({"wp-json": wp, "b.hr": rss, "dobrinj": page, "pgz": page})
    reader = Reader(http, Locator())
    items = reader.fetch({"naziv": "Općina Malinska-Dubašnica", "jls": "Malinska-Dubašnica", "nacin": "wp", "url": "https://m.hr/"})
    assert [t.title for t in items] == ["Natječaj za prodaju nekretnine – Učiteljska"]
    assert items[0].published == "2026-09-21" and "k.č. 12/3" in items[0].text
    items = reader.fetch({"naziv": "Općina Baška", "jls": "Baška", "nacin": "rss", "url": "https://b.hr/"})
    assert items[0].published == "2026-09-21" and items[0].url == "https://b.hr/n1"
    items = reader.fetch({"naziv": "Općina Dobrinj", "jls": "Dobrinj", "nacin": "stranica", "url": "https://dobrinj.hr/natj"})
    assert [t.url for t in items] == ["https://dobrinj.hr/natjecaj-zemljiste", "https://dobrinj.hr/x.pdf"]
    # Regionalno tijelo: zadržava se samo objava koja spominje naše područje.
    items = reader.fetch({"naziv": "PGŽ", "nacin": "stranica", "url": "https://www.pgz.hr/natj"})
    assert [(t.title, t.jls) for t in items] == [("NATJEČAJ-prodaja zemljišta u Dobrinju", "Dobrinj")]


def test_format_tender():
    t = Tender("k", "Općina Vrbnik", "Vrbnik", "NATJEČAJ ZA PRODAJU ZEMLJIŠTA k.č. 788/2 k.o. VRBNIK", "https://v.hr/n",
               "2026-09-21", "Predmet natječaja je prodaja zemljišta. " * 10)
    text = format_tender(t, {"rok": "2026-10-15", "cijene": [45000.0], "povrsine": [612.0]},
                         ["🗺 k.č. 788/2 k.o. VRBNIK (612 m²): u građevinskom području naselja (izgrađeni dio) · PPV 74–86 €/m²"])
    assert text.splitlines() == [
        "📜 <b>Natječaj za prodaju</b> · Općina Vrbnik",
        "<b>NATJEČAJ ZA PRODAJU ZEMLJIŠTA k.č. 788/2 k.o. VRBNIK</b>",
        "📅 objavljeno 21. 9. 2026. · ⏳ rok 15. 10. 2026.",
        "💶 početna cijena 45.000 € · 612 m²",
        "🗺 k.č. 788/2 k.o. VRBNIK (612 m²): u građevinskom području naselja (izgrađeni dio) · PPV 74–86 €/m²"]


def test_runner_tenders_first_day_and_later(tmp_path, monkeypatch):
    from scraper.db import State
    from scraper.runner import Runner

    recent, old = (TODAY - timedelta(days=5)).isoformat(), (TODAY - timedelta(days=200)).isoformat()
    future = (TODAY + timedelta(days=10)).strftime("%d.%m.%Y.")
    batch = [Tender("a", "Grad Krk", "Krk", "Natječaj za prodaju zemljišta A", "https://k.hr/a", recent, f"Rok za ponude {future}"),
             Tender("b", "Grad Krk", "Krk", "Natječaj za prodaju zemljišta B", "https://k.hr/b", old, "stari"),
             Tender("c", "Grad Krk", "Krk", "Natječaj za prodaju zemljišta C", "https://k.hr/c", recent, "Rok za ponude 1.1.2020.")]

    class FakeReader:
        def __init__(self, *a):
            pass

        def fetch(self, site):
            return list(batch)

        def load_text(self, t):
            pass

    sent = []

    class FakeTelegram:
        def send_text(self, text, silent=False, url=""):
            sent.append((text, url))

    monkeypatch.setattr(tenders, "Reader", FakeReader)
    monkeypatch.setattr(tenders, "load_sites", lambda: [{"naziv": "Grad Krk", "jls": "Krk", "nacin": "wp", "url": "u"}])
    runner = Runner(tmp_path / "s.db", tmp_path, send=False)
    runner.telegram = FakeTelegram()
    state = State(tmp_path / "s.db")
    runner._tenders(state)
    assert [u for _, u in sent] == ["https://k.hr/a"]        # prvi dan: samo nedavni s otvorenim rokom
    runner._tenders(state)
    assert len(sent) == 1                                      # isti dan se ne čita ponovno
    state.meta_set("daily:natjecaji", "2000-01-01")
    batch.append(Tender("d", "Grad Krk", "Krk", "Natječaj za prodaju kuće D", "https://k.hr/d", old, ""))
    runner._tenders(state)
    assert [u for _, u in sent] == ["https://k.hr/a", "https://k.hr/d"]   # poslije: svaka nova objava
