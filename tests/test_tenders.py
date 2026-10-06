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
    assert relevant("Javni poziv za podnošenje ponuda za kupnju nekretnina u vlasništvu CERP-a")
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
            "<a href='/x.pdf'>Natječaj za prodaju nekretnine u Zagrebu</a>")
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


def test_lots_pair_price_and_area_with_parcel():
    from scraper.tenders import lots

    found = lots("Predmet prodaje: 1. k.č. 1234/5 k.o. Njivice, površine 650 m², početna cijena 65.000,00 EUR. "
                 "2. k.č. 1234/6 k.o. Njivice, površine 900 m2, početna cijena 81.000,00 EUR. Jamčevina 10 %.")
    assert [(x.kcs, x.price, x.area, x.unit_price) for x in found] == [
        (["1234/5"], 65000.0, 650.0, 100.0), (["1234/6"], 81000.0, 900.0, 90.0)]
    # Vrijednosti ispred čestice.
    found = lots("Zemljište površine 650 m² i početne cijene od 65.000 EUR, označeno kao k.č. 100 k.o. Vrbnik; "
                 "zemljište površine 900 m², početna cijena 90.000 EUR, k.č. 200 k.o. Vrbnik.")
    assert [(x.kcs, x.price, x.area) for x in found] == [(["100"], 65000.0, 650.0), (["200"], 90000.0, 900.0)]
    # Cijena po m², dio čestice; kuća; nejasno (dvije cijene za istu česticu).
    (lot,) = lots("Prodaje se dio k.č. 55/1 k.o. Punat površine 300 m2. Početna cijena iznosi 150,00 EUR/m2.")
    assert (lot.ppm, lot.area, lot.unit_price, lot.house) == (150.0, 300.0, 150.0, False)
    (lot,) = lots("Prodaje se obiteljska kuća na k.č. 77 k.o. Dobrinj, početna cijena za k.č. 77 iznosi 150.000 EUR.")
    assert (lot.house, lot.price) == (True, 150000.0)
    (lot,) = lots("k.č. 9 k.o. Baška: početna cijena 10.000 EUR, a nakon prvog kruga početna cijena 8.000 EUR.")
    assert lot.price is None


def test_details_price_per_m2():
    assert details("Početna cijena iznosi 85,00 €/m2, rok za ponude 1. 12. 2026.") == {
        "rok": "2026-12-01", "cijene_m2": [85.0]}


def test_format_tender():
    t = Tender("k", "Općina Vrbnik", "Vrbnik", "NATJEČAJ ZA PRODAJU ZEMLJIŠTA k.č. 788/2 k.o. VRBNIK", "https://v.hr/n",
               "2026-09-21", "Predmet natječaja je prodaja zemljišta. " * 10)
    lot = tenders.Lot("VRBNIK", ["788/2"], price=45000.0, cadastre_area=612.0,
                      gp="u građevinskom području naselja (izgrađeni dio)",
                      notes=["🏛 PPV 2026. (na lokaciji, blok Vrbnik): građevinsko 74–86 €/m² – početna cijena u rasponu"])
    text = format_tender(t, {"rok": "2026-10-15", "cijene": [45000.0], "povrsine": [612.0], "dio": True}, [lot],
                         "📊 more 0,4 km · PPV u rasponu · ⚠ 1", "Vrbnik – Vrbnik", ["prodaje se dio nekretnine – provjeri"])
    assert text.splitlines() == [
        "📜 <b>Natječaj za prodaju</b> · Općina Vrbnik",
        "<b>NATJEČAJ ZA PRODAJU ZEMLJIŠTA k.č. 788/2 k.o. VRBNIK</b>",
        "📊 more 0,4 km · PPV u rasponu · ⚠ 1",
        "📅 objavljeno 21. 9. 2026. · ⏳ rok 15. 10. 2026.",
        "📍 Vrbnik – Vrbnik",
        "🗺 k.č. 788/2 k.o. VRBNIK (612 m²): u građevinskom području naselja (izgrađeni dio)",
        "💶 početna cijena 45.000 € · 74 €/m²",
        "🏛 PPV 2026. (na lokaciji, blok Vrbnik): građevinsko 74–86 €/m² – početna cijena u rasponu",
        "⚠ prodaje se dio nekretnine – provjeri"]
    # Bez čestica: cijene i površine iz teksta.
    text = format_tender(t, {"cijene": [45000.0], "povrsine": [612.0]})
    assert "💶 početna cijena 45.000 € · 612 m²" in text.splitlines()


def test_runner_tender_message_with_parcels(tmp_path):
    from scraper.ispu import PointInfo
    from scraper.models import LAND
    from scraper.prices import AskingPrices
    from scraper.runner import Runner

    class FakeIspu:
        def parcel(self, ko, kc, names=None):
            return {"x": 1.0, "y": 2.0, "povrsina": {"1234/5": 650, "1234/6": 900}[kc]}

        def identify(self, x, y):
            return PointInfo(gp="naselja", use="(GP) NEIZGRAĐENI DIO GRAĐEVINSKOG PODRUČJA NASELJA",
                             block="NJIVICE - GRAĐEVINSKO", land_values=[158.0, 219.0])

    runner = Runner(tmp_path / "s.db", tmp_path, send=False)
    runner._ispu = FakeIspu()
    prices = AskingPrices(runner.locator, {f"{LAND}|Omišalj|njivice": {"n": 20, "med": 200}})
    text = "Predmet prodaje: k.č. 1234/5 k.o. Njivice, početna cijena 65.000,00 EUR."
    t = Tender("n1", "Općina Omišalj", "Omišalj", "Natječaj za prodaju zemljišta u Njivicama", "https://o.hr/n1",
               TODAY.isoformat(), text)
    found = tenders.lots(text)
    message = runner._tender_message(t, tenders.details(text), found, "Omišalj", tenders.place_text(t, found), None,
                                     prices, 10 ** 12)
    lines = message.splitlines()
    assert lines[2] == "📊 more 0,3 km · Rijeka 35 min · Zagreb 2 h 18 min · cijena −50 % od prosjeka · PPV −35 %"
    assert lines[4:9] == [
        "📍 Omišalj – Njivice",
        "🗺 k.č. 1234/5 k.o. Njivice (650 m²): u građevinskom području naselja (neizgrađeni dio)",
        "💶 početna cijena 65.000 € · 100 €/m²",
        "🏛 PPV 2026. (na lokaciji, blok Njivice - Građevinsko): građevinsko 158–219 €/m² – početna cijena 35 % ispod donje",
        "💰 50 % ispod medijana traženih (Njivice: 200 €/m², 20 oglasa)"]


def test_runner_tenders_first_day_and_later(tmp_path, monkeypatch):
    from scraper.db import State
    from scraper.runner import Runner

    recent, old = (TODAY - timedelta(days=5)).isoformat(), (TODAY - timedelta(days=200)).isoformat()
    future = (TODAY + timedelta(days=10)).strftime("%d.%m.%Y.")
    older = (TODAY - timedelta(days=90)).isoformat()
    batch = [Tender("a", "Grad Krk", "Krk", "Natječaj za prodaju zemljišta A", "https://k.hr/a", recent, f"Rok za ponude {future}"),
             # Naselje isključeno popisom (napisano u tekstu) → bez poruke; samo prema k.o. → ⚠.
             Tender("r", "Grad Krk", "Krk", "Natječaj za prodaju zemljišta u naselju Muraj", "https://k.hr/r", recent, "x"),
             Tender("k", "Grad Krk", "Krk", "Natječaj za prodaju zemljišta K", "https://k.hr/k", recent, "Prodaje se k.č. 5 k.o. Muraj."),
             Tender("b", "Grad Krk", "Krk", "Natječaj za prodaju zemljišta B", "https://k.hr/b", old, "stari"),
             Tender("c", "Grad Krk", "Krk", "Natječaj za prodaju zemljišta C", "https://k.hr/c", recent, "Rok za ponude 1.1.2020."),
             Tender("e", "Grad Krk", "Krk", "Natječaj za prodaju zemljišta E", "https://k.hr/e", older, f"Rok za ponude {future}")]

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
    assert [u for _, u in sent] == ["https://k.hr/a", "https://k.hr/k", "https://k.hr/e"]   # prvi dan: rok nije istekao
    assert "⚠ Muraj: isključeno po popisu naselja" in sent[1][0] and "prema k.o." in sent[1][0]
    runner._tenders(state)
    assert len(sent) == 3                                      # isti dan se ne čita ponovno
    state.meta_set("daily:natjecaji", "2000-01-01")
    batch.append(Tender("d", "Grad Krk", "Krk", "Natječaj za prodaju kuće D", "https://k.hr/d", old, ""))
    runner._tenders(state)
    assert [u for _, u in sent][-1] == "https://k.hr/d" and len(sent) == 4   # poslije: svaka nova


# Isječci iz stvarnih natječaja (listopad 2026.).
PUNAT = ("Predmet natječaja je: Prodaja nekretnine u vlasništvu Općine Punat: k.č. 4784/4 , oranica površine 222 m², "
         "zk.ul. 7471 k.o. Punat Početna natječajna cijena određuje se u iznosu od 190,00 EUR/m². Ponude se dostavljaju "
         "u zatvorenoj omotnici s naznakom: «Ponuda za kupnju nekretnine po natječaju – ne otvarati» na adresu: OPĆINA "
         "PUNAT Novi put 2 51521 Punat Ponude se predaju neposredno na urudžbeni zapisnik ili putem pošte preporučenom "
         "pošiljkom, a krajnji rok za dostavu ponuda je 8 (osmi) dan od dana objave obavijesti o natječaju u „Novom listu“ "
         "do 13,00 sati neovisno o načinu dostave. Obavijest o raspisanom natječaju objavit će se u „Novom listu“ dana "
         "16. rujna 2026. godine .")
OPATIJA = ("I. PREDMET PRODAJE : k. č. 159/3 pašnjak od 154 m2, upisana u zk.ul. 1764 k.o. Volosko k. č. 172/4 šuma od "
           "47 m2, upisana u zk.ul. 883 k.o. Volosko NAPOMENA: predmetne nekretnine prodaju se kao cjelina Početna cijena: "
           "101.141,63 eura (slovima: stojednatisuća) Jamčevina: 10.114,16 eura. Pod dokazom o plaćenoj jamčevini smatra "
           "se i garancija banke s rokom važenja do 31. listopada 2026. godine. III. ROK ZA PODNOŠENJE PONUDA: Ponuda s "
           "prilozima dostavlja se u roku od 15 dana od dana objave, odnosno, zaključno s 20.7.2026. godine.")
LOVRAN = ("PRIKUPLJANJEM PISANIH PONUDA ZA PRODAJU: k.č. 4312, upisana u ZK uložak 1760, k.o. Lovran, pašnjak, 10 m 2 , "
          "radi ostvarenja prilaza, po početnoj cijeni od 596,00 eur. Natječaj se provodi izborom najpovoljnijeg ponuđača "
          "na temelju pisanih ponuda predanih u roku od 15 dana, računajući od dana objave Obavijesti o provođenju "
          "natječajnog postupka u dnevnom glasilu Novi list Rijeka, dana 29. ožujka 2026. godine , i to u zatvorenoj koverti.")
MALINSKA = ("na prodaju se nudi slijedeća nekretnina: – cijela k.č. 3574/2 k.o. Malinska – Dubašnica, upisana u z.k.ul. "
            "2717 kod Općinskog suda u Crikvenici, opisane kao MATE BALOTE površine 22 m2 od čega DVORIŠTE površine 22 m2, "
            "po početnoj cijeni zemljišta utvrđenoj prema Procjembenom elaboratu tržišne vrijednosti građevinskog "
            "zemljišta br. 005/2024 od 15. svibnja 2024. godine izrađenom od sudskog vještaka iz Rijeke, u iznosu od "
            "ukupno 4.300,00 € (slovima: četiritisućetristoeura).")
CRIKVENICA = ("1. suvlasničkog dijela nekretnine označene kao zk.č.br. 1523 (k.č.br.2775/3) – G. Kovačevac – uređeno "
              "zemljište, ukupne površine 398 m 2 i to suvlasničkog dijela Grada Crikvenice u udjelu od 6/240 odnosno "
              "ukupne površine 9,95 m2 iz zk.ul. 6835 k.o. Crikvenica - početna kupoprodajna cijena iznosi 100,00 eura/m2. "
              "Ponude se predaju u roku 8 dana od dana objave obavijesti o natječaju u novinama, zaključno do 6. listopada "
              "2026. godine do 10,00 sati.")


def test_real_tender_texts():
    from scraper.ispu import parcel_mentions
    from scraper.tenders import fails_criteria, flats_only, lots

    (lot,) = lots(PUNAT)
    assert (lot.label, lot.ppm, lot.area) == ("k.č. 4784/4 k.o. Punat", 190.0, 222.0)
    assert details(PUNAT)["rok"] == "2026-09-24" and details(PUNAT)["rok_priblizno"]
    (lot,) = lots(OPATIJA)             # dvije čestice kao cjelina: jedna cijena za 201 m²
    assert (lot.label, lot.price, lot.area, lot.parts) == ("k.č. 159/3, 172/4 k.o. Volosko", 101141.63, 201.0, 2)
    assert details(OPATIJA)["rok"] == "2026-07-20" and "rok_priblizno" not in details(OPATIJA)
    (lot,) = lots(LOVRAN)
    assert (lot.price, lot.area) == (596.0, 10.0)
    assert details(LOVRAN)["rok"] == "2026-04-13"
    (lot,) = lots(MALINSKA)
    assert (lot.label, lot.price, lot.area) == ("k.č. 3574/2 k.o. Malinska-Dubašnica", 4300.0, 22.0)
    # Zemljišnoknjižna oznaka uz katastarsku: vrijedi katastarska.
    assert [(m.ko, m.kcs, m.land_registry) for m in parcel_mentions(CRIKVENICA)] == [("Crikvenica", ["2775/3"], False)]
    assert details(CRIKVENICA)["rok"] == "2026-10-06"
    assert [(m.ko, m.land_registry) for m in parcel_mentions("122/18805 dijela z.č. 746/3, pašnjak, zk.ul. 4520 k.o. Stara Baška")] \
        == [("Stara Baška", True)]
    assert parcel_mentions("k.č. 3842/1 k.o. Sv. Jelena, površine 274 m2")[0].ko == "Sv. Jelena"
    criteria = {"kuca": {"min_povrsina": 70, "max_cijena": 400000}, "zemljiste": {"min_povrsina": 300, "max_cijena": 300000}}
    assert fails_criteria(lots(MALINSKA), criteria) == "k.č. 3574/2 k.o. Malinska-Dubašnica: 22 m²"
    assert fails_criteria(lots(PUNAT), criteria)              # 222 m²
    assert not fails_criteria(lots("k.č. 77 k.o. Dobrinj, obiteljska kuća, početna cijena 150.000 EUR"), criteria)
    assert flats_only("ZAGREB - ANTUNA BAUERA 28 (STAN 2473)* Površina 32,36 m2 Početna cijena 71.100,00 EUR. "
                      "Nekretnina je upisana u Zemljišnoknjižnom odjelu, kč.br. 6125")
    assert not flats_only(OPATIJA)


def test_shares_groups_and_docx():
    import io as _io
    import zipfile

    from scraper.ispu import parcel_mentions
    from scraper.tenders import lots

    # "7/9 dijela" je udio, ne čestica.
    assert [m.kcs for m in parcel_mentions("prodaja 126/576 dijela k.č.br. 2977 i 7/9 dijela k.č.br. 2978 k.o. Kostrena-Lucija")] \
        == [["2977"], ["2978"]]
    # Zbirni spomen koji ponavlja pojedinačne čestice se ne broji kao nova čestica.
    found = lots("k.č. 5210 k.o. Kostrena-Lucija površine 35 m2, k.č. 5211 k.o. Kostrena-Lucija površine 14 m2. "
                 "Čestice k.č. 5210 i 5211 k.o. Kostrena-Lucija nalaze se uz cestu.")
    assert [x.kcs for x in found] == [["5210"], ["5211"]]
    # Word prilog (.docx) se čita.
    buf = _io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", "<w:document><w:body><w:p><w:r><w:t>Prodaje se k.č. 1268/5 K.O. Matulji,</w:t></w:r>"
                                        "</w:p><w:p><w:r><w:t>početna cijena 50.000,00 EUR.</w:t></w:r></w:p></w:body></w:document>")

    class Bin:
        content = buf.getvalue()

    class Http:
        def get(self, url, **kw):
            return Bin()

    text = Reader(Http(), Locator()).doc_text("https://matulji.hr/a/Javni-natjecaj.docx")
    assert text == "Prodaje se k.č. 1268/5 K.O. Matulji, početna cijena 50.000,00 EUR."
    assert details(text)["cijene"] == [50000.0]


def test_page_links_filter():
    page = ('<a href="/gradska-uprava/natjecaji-2/raspolaganje-zemljistem-prodaja/">Raspolaganje zemljištem – prodaja, pravo '
            'građenja, služnosti i zakup</a><a href="/bidding/natjecaj-za-prodaju-zemljista/">Natječaj za prodaju zemljišta u '
            'vlasništvu Grada Rijeke</a>')
    reader = Reader(FakeHttp({"rijeka": page}), Locator())
    items = reader.fetch({"naziv": "Grad Rijeka (ostali)", "jls": "Rijeka", "nacin": "stranica", "poveznice": "/bidding/",
                          "url": "https://www.rijeka.hr/gradska-uprava/natjecaji-2/ostali-natjecaji/"})
    assert [t.url for t in items] == ["https://www.rijeka.hr/bidding/natjecaj-za-prodaju-zemljista/"]
