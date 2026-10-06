"""Parseri na spremljenim stvarnim stranicama (tests/fixtures)."""

import gzip
import json
from pathlib import Path

import pytest

from scraper.locations import Locator
from scraper.models import HOUSE, LAND
from scraper.runner import load_config
from scraper.sources import index_oglasi, nekretnine_hr, oglasnik
from scraper.sources.fina import Fina

FIX = Path(__file__).parent / "fixtures"


def read(name):
    return gzip.open(FIX / name).read().decode("utf-8")


def test_nekretnine_hr_houses():
    items, pages = nekretnine_hr.parse_page(read("nekretnine_kuce_pgz.html.gz"), HOUSE)
    assert len(items) == 25 and pages > 100
    kostrena = next(x for x in items if x.source_id == "3273189")
    assert kostrena.municipality == "Kostrena" and kostrena.price == 580000 and kostrena.area == 150
    assert kostrena.url.startswith("https://www.nekretnine.hr/oglasi/")
    assert all(x.county == "Primorsko-goranska" for x in items)


def test_nekretnine_hr_land():
    items, _ = nekretnine_hr.parse_page(read("nekretnine_zemljista_pgz.html.gz"), LAND)
    assert any(x.subtype == "Građevinsko zemljište" and x.area == 1200 for x in items)


def test_oglasnik_houses():
    items = oglasnik.parse_page(read("oglasnik_kuce.html.gz"), HOUSE)
    assert len(items) == 100
    x = next(i for i in items if i.source_id == "7145878")
    assert x.subtype == "dvojni objekt" and x.area == pytest.approx(309.31) and x.plot_area == 248
    assert x.county == "Primorsko-goranska" and x.municipality == "Crikvenica"
    assert x.price == 480000 and "dvojne kuće" in x.description
    assert x.url.endswith("-oglas-7145878") and x.image_url.startswith("https://")


def test_oglasnik_land():
    items = oglasnik.parse_page(read("oglasnik_zemljista.html.gz"), LAND)
    assert len(items) > 50 and any(x.area for x in items)


def test_index_items():
    data = json.loads(read("index_kuce.json.gz"))
    items = index_oglasi.parse_items(data, "prodaja-kuca", HOUSE)
    x = items[0]
    assert x.source_id == "7542932" and x.price == 690000 and x.area == 400
    assert x.url == "https://www.index.hr/oglasi/nekretnine/prodaja-kuca/oglas/visestambena-kamena-kuca-s-bazenom-i-pogledom-na-more-supetar/7542932"
    assert x.municipality == "Supetar" and x.county == "Splitsko-dalmatinska"


@pytest.fixture(scope="module")
def fina():
    return Fina(None, Locator(), load_config()["kriteriji"])


def row(court, opis, price="90000.00"):
    return {"Nadležno tijelo": court, "Poslovni broj spisa": "Ovr-1/2026", "Opis": opis,
            "Vrsta predmeta prodaje": "nekretnina", "Početna cijena za nadmetanje": price}


def test_fina_regional_court_and_cadastral(fina):
    x = fina.to_listing(row("Općinski sud u Crikvenici, Stalna služba u Krku",
                            "Građevinsko zemljište, k.č. 1234, k.o. Punat, površine 620 m2"))
    assert x.municipality == "Punat" and x.area == 620 and x.price == 90000 and not x.extra["reject"]


def test_fina_cadastral_name_differs_from_municipality(fina):
    x = fina.to_listing(row("Općinski sud u Rijeci", "građevinsko zemljište k.o. Novi, 300 čhv"))
    assert x.municipality == "Novi Vinodolski" and round(x.area) == 1079


def test_fina_same_name_elsewhere_rejected(fina):
    x = fina.to_listing(row("Općinski sud u Splitu", "Građevinsko zemljište, k.o. Baška Voda, 500 m2"))
    assert x is None or x.extra["reject"] or not x.municipality


def test_fina_bankruptcy_elsewhere_warns(fina):
    x = fina.to_listing(row("Trgovački sud u Zagrebu", "zemljište u građevinskom području, k.o. Crikvenica, 1.250 m²"))
    assert x.municipality == "Crikvenica" and any("stečaj" in w for w in x.extra["warnings"])


def test_fina_unrelated_items_skipped(fina):
    assert fina.to_listing(row("Općinski sud u Osijeku", "građevinsko zemljište k.o. Tenja, 800 m2")) is None
    assert fina.to_listing(row("Općinski sud u Rijeci", "stan u Rijeci, 54 m2")) is None


def test_fina_partial_cadastral_name_not_matched(fina):
    # "Donje Polje" (Šibenik) nije Dobrinjsko naselje Polje.
    x = fina.to_listing(row("Općinski sud u Šibeniku", "građevinsko zemljište, k.o. Donje Polje u prizemlju, 500 m2"))
    assert x is None


def test_fina_cadastral_variants(fina):
    x = fina.to_listing(row("Općinski sud u Rijeci", "građevinsko zemljište k.o. Kostrena-Lucija, 450 m2"))
    assert x.municipality == "Kostrena" and x.title.count("k.o.") == 1
    x = fina.to_listing(row("Općinski sud u Crikvenici, Stalna služba u Krku", "građevinsko zemljište k.o. Omišalj-Njivice, 700 m2"))
    assert x.municipality == "Omišalj"


def test_vender_items():
    from scraper.sources.vender import parse_items

    items = {x.source_id: x for x in parse_items(json.loads(gzip.open(FIX / "vender_pgz.json.gz").read()))}
    assert len(items) == 20
    drenova = items["789991"]
    assert drenova.kind == HOUSE and drenova.subtype == "Kuća u nizu"
    assert drenova.price == 499000 and drenova.area == 148 and drenova.plot_area == 52
    assert drenova.municipality == "Rijeka" and drenova.settlement == "Drenova"
    assert items["790712"].settlement == "Barbat Na Rabu" and items["790712"].area is None
    assert sum(x.kind == HOUSE for x in items.values()) == 5



def test_njuskalo_list_houses():
    from scraper.sources.njuskalo import parse_list

    items = {x.source_id: x for x in parse_list(read("njuskalo_kuce.html.gz"), HOUSE)}
    assert len(items) == 31 and sum(x.extra["istaknut"] for x in items.values()) == 6
    x = items["45131418"]
    assert x.subtype == "Samostojeća kuća" and x.price == 500000 and x.area == 157
    assert (x.municipality, x.settlement) == ("Krk", "Krk") and x.published.startswith("2026-10-05T09:27")
    assert x.url == "https://www.njuskalo.hr/nekretnine/sarmantna-samostojeca-kuca-okolici-grada-krka-oglas-45131418"
    assert items["44223167"].subtype == "U nizu kuća"
    assert items["41395237"].municipality == "Opatija - Okolica"


def test_njuskalo_list_land_area_from_title():
    from scraper.sources.njuskalo import parse_list

    items = {x.source_id: x for x in parse_list(read("njuskalo_zemljista.html.gz"), LAND)}
    assert items["51465742"].area == 965 and items["42353257"].area == 758
    assert items["47267864"].area is None  # naslov bez površine – dopunjuje se sa stranice oglasa


def test_njuskalo_detail():
    from scraper.sources.njuskalo import parse_detail, parse_list

    house = next(x for x in parse_list(read("njuskalo_kuce.html.gz"), HOUSE) if x.source_id == "45131418")
    parse_detail(read("njuskalo_kuca_oglas.html.gz"), house)
    assert house.subtype == "Samostojeća kuća" and house.area == 157 and house.plot_area == 250
    assert house.extra["parking"] == "2" and house.extra["priblizna_lokacija"] is True
    assert round(house.extra["lat"], 3) == 45.029 and "4 km od mora" in house.description
    land = next(x for x in parse_list(read("njuskalo_zemljista.html.gz"), LAND) if x.source_id == "51465742")
    parse_detail(read("njuskalo_zemljiste_oglas.html.gz"), land)
    assert land.subtype == "Građevinsko zemljište" and land.area == 965 and land.extra["namjena"] == "stambeno"


class FakeBrowser:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def get(self, url, wait_selector="body"):
        self.calls.append(url)
        for key, page in self.pages.items():
            if key in url:
                return page
        return "<html><title>prazno</title></html>"

    def close(self):
        pass


def test_njuskalo_fetch_old_and_new(fina):
    from scraper.sources.base import INCREMENTAL
    from scraper.sources.njuskalo import Njuskalo

    browser = FakeBrowser({"prodaja-kuca": read("njuskalo_kuce.html.gz"),
                           "prodaja-zemljista": read("njuskalo_zemljista.html.gz"),
                           "oglas-51323938": read("njuskalo_kuca_oglas.html.gz")})
    src = Njuskalo(None, Locator(), load_config()["kriteriji"], browser=browser)
    src.since = "2026-10-05T11:30:00+02:00"
    # Već viđen oglas s brojem 45.180.000: sve s brojem ≤ 45.120.000 je "staro".
    items = {x.source_id: x for x in src.fetch(INCREMENTAL, {"45180000"})}
    assert items["41395237"].extra.get("stari_oglas") and items["45131418"].extra.get("stari_oglas") is None
    # Rijeka, 368.000 €: nov i mogao bi proći → otvara se oglas; Krk, 500.000 €: preskupo → ne otvara se.
    assert items["51323938"].extra.get("detalji") and items["51323938"].plot_area == 250
    assert "detalji" not in items["45131418"].extra
    detail_calls = [u for u in browser.calls if "/nekretnine/" in u]
    assert not any(sid in u for u in detail_calls for sid in ("47749178", "41395237"))  # izvan područja / stari
    assert not any("oglas-50785229" in u for u in detail_calls)  # dvojna kuća → ne otvara se
    assert 0 < len(detail_calls) <= 8  # samo oglasi koji bi mogli proći, najviše 8
    assert sum("prodaja-kuca" in u for u in browser.calls) == 1  # najstariji na 1. stranici je stariji od since


class FakeHttp:
    """Popis i oglasi index.hr bez mreže; bilježi pozive."""

    def __init__(self, items, ads):
        self.items, self.ads, self.calls = items, ads, []

    def get(self, url, **kwargs):
        self.calls.append(url)

        class Resp:
            def __init__(self, data):
                self.data = data

            def json(self):
                return self.data

        if "single-ad" in url:
            return Resp({"data": [self.ads[url.split("code=")[1].split("&")[0]]]})
        if "category=houses-for-sale" in url:
            return Resp({"data": self.items, "nextPage": -1})
        return Resp({"data": [], "nextPage": -1})


def test_index_opens_new_matching_ads():
    from scraper.filters import evaluate
    from scraper.models import REJECT, WARN
    from scraper.sources.base import INCREMENTAL

    def item(code, price, city="Omišalj", settlement="Njivice"):
        return {"code": code, "title": f"Kuća {settlement}", "price": price, "summary": {"area": 120},
                "countyName": "Primorsko-goranska", "cityName": city, "settlementName": settlement, "smartLink": "k"}

    items = [item(1, 300_000), item(2, 290_000), item(3, 900_000), item(4, 250_000, "Ravna Gora", "Ravna Gora"),
             item(5, 280_000)]
    ads = {"1": {"description": "Lijepa kuća. Kuća je u suvlasništvu s bratom.", "houseType": 1, "gardenArea": 400,
                 "yearBuilt": "1978-01-01T00:00:00Z", "noEnclosedCarPark": True, "ownershipCertificate": True},
           "2": {"description": "Dvojna kuća u mirnom dijelu.", "houseType": 2}}
    http = FakeHttp(items, ads)
    cfg = load_config()["kriteriji"]
    src = index_oglasi.IndexOglasi(http, Locator(), cfg)
    found = {x.source_id: x for x in src.fetch(INCREMENTAL, {"5"})}
    opened = [u for u in http.calls if "single-ad" in u]
    # Otvaraju se samo novi oglasi koji bi mogli proći: ne preskup, ne izvan područja, ne već poznat.
    assert sorted(u.split("code=")[1][0] for u in opened) == ["1", "2"]
    x1, x2 = found["1"], found["2"]
    assert x1.subtype == "Samostojeća kuća" and x1.plot_area == 400 and x1.extra["parking"] == "vanjsko parkirno mjesto"
    assert x1.extra["godina_izgradnje"] == 1978 and x1.extra["vlasnicki_list"]
    d1 = evaluate(x1, cfg, Locator())
    assert d1.status == WARN and any(w.startswith("suvlasništvo") for w in d1.warnings)
    assert evaluate(x2, cfg, Locator()).status == REJECT  # dvojna kuća iz vrste u oglasu


def test_nekretnine_detail():
    from scraper.models import Listing
    from scraper.sources.nekretnine_hr import parse_detail

    data = {"props": {"pageProps": {"detailData": {"realEstate": {"properties": [{
        "caption": "Kuća Njivice", "description": "Puni opis kuće. Kuća je u suvlasništvu.",
        "features": ["Konoba", "Garaža"], "primaryFeatures": [{"name": "balkon", "value": 1}],
        "buildingYear": 1987, "land": "420 m²"}]}, "trovakasa": {"boxAutoId": None}}}}}
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'
    x = Listing(source="nekretnine_hr", source_id="1", url="u", title="Kuća", kind=HOUSE, description="Puni op",
                extra={"opis_skracen": True})
    parse_detail(html, x)
    assert x.description == "Kuća Njivice Puni opis kuće. Kuća je u suvlasništvu."
    assert x.extra["parking"] == "garaža" and x.extra["godina_izgradnje"] == 1987 and x.plot_area == 420
    assert "opis_skracen" not in x.extra and x.extra["detalji"]


def test_realestatecroatia_list_detail_and_incremental():
    from scraper.sources.realestatecroatia import RealEstateCroatia, parse_detail, parse_list

    page = read("realestatecroatia_kuce.html.gz")
    items = {x.source_id: x for x in parse_list(page, HOUSE)}
    assert len(items) == 20
    x = items["1312906"]
    assert (x.price, x.settlement, x.location_text, x.subtype) == (360000, "Čižići", "Čižići (Krk)", "Kuća")
    assert x.extra["agencija"] == "PREMIUM nekretnine" and x.extra["istaknut"]
    parse_detail(read("realestatecroatia_oglas.html.gz"), items["1311438"])
    y = items["1311438"]
    assert (y.area, y.plot_area) == (86, 170) and y.description.startswith("Okolica Malinske")
    assert "opis_skracen" not in y.extra and "/thumbnails/userimages/" in y.image_url

    class Resp:
        def __init__(self, text):
            self.text = text

    class Http:
        def __init__(self):
            self.urls = []

        def get(self, url, **kw):
            self.urls.append(url)
            if "detail.asp" in url:
                return Resp(read("realestatecroatia_oglas.html.gz"))
            return Resp(page if "vrsta=1" in url else "")

    http = Http()
    cfg = load_config()
    src = RealEstateCroatia(http, Locator(), cfg["kriteriji"])
    known = {k for k, v in items.items() if not v.extra["istaknut"]}       # svi neistaknuti već poznati
    found = src.fetch("incremental", known)
    assert sum("list.asp" in u for u in http.urls) == 2                   # kuće str. 1 (stop) + zemljišta str. 1
    assert all(x.price for x in found)                                    # "cijena na upit" preskočena
    assert len([u for u in http.urls if "detail.asp" in u]) <= 10


def test_burza_list_detail_and_fetch():
    from scraper.models import Listing
    from scraper.sources import burza

    page = read("burza_kuce.html.gz")
    items = {x.source_id: x for x in burza.parse_list(page, HOUSE, "Crikvenica")}
    assert len(items) == 6 and items["349053"].price is None                 # "cijena na upit"
    x = items["347113"]
    assert (x.price, x.area, x.settlement) == (420000, 120, "Crikvenica") and x.extra["opis_skracen"]
    assert x.url.startswith("https://burza.com.hr/oglasi/") and x.url.endswith("/347113")
    assert burza.parse_list(page, HOUSE, "otok Krk")[0].settlement == ""       # otok nije naselje

    y = Listing("burza", "1", "https://burza.com.hr/oglasi/x/1", "Crikvenica, 435m2, samostojeća kuća", HOUSE, price=875000)
    burza.parse_detail(read("burza_oglas.html.gz"), y)
    assert (y.settlement, y.area, y.published) == ("Crikvenica", 435, "2026-10-05")
    assert y.extra["oglasivac"].startswith("Millennium") and "opis_skracen" not in y.extra
    assert y.description.startswith("Prodaje se velika samostojeća kuća")
    assert burza._areas("Prodaje se kuća na okućnici od 600 m2, stambene površine 150 m2", HOUSE) == (150, 600)

    class Resp:
        def __init__(self, text):
            self.text = text

    class Http:
        def __init__(self):
            self.urls = []

        def get(self, url, **kw):
            self.urls.append(url)
            if url.rstrip("/").split("/")[-1].isdigit():
                return Resp(read("burza_oglas.html.gz"))
            return Resp(page if "kuce" in url and ("crikvenica" in url or url.endswith("kvarner-i-istra")) else "")

    cfg = load_config()
    http = Http()
    found = burza.Burza(http, Locator(), cfg["kriteriji"]).fetch("full", set())
    assert {x.source_id for x in found} == {"350166", "350164", "347113", "350118"}   # bez "na upit"
    assert sum(u.split("/")[-1].isdigit() for u in http.urls) == 4                # svaki oglas otvoren
    assert all(x.settlement == "Crikvenica" and x.published for x in found)

    http = Http()
    known = {"350166", "350164"}
    found = {x.source_id: x for x in burza.Burza(http, Locator(), cfg["kriteriji"]).fetch("incremental", known)}
    assert set(found) == {"350166", "350164", "347113", "350118"}
    assert found["350166"].settlement == "" and found["350166"].extra["opis_skracen"]   # poznat: bez otvaranja
    assert sorted(u.split("/")[-1] for u in http.urls if u.split("/")[-1].isdigit()) == ["347113", "350118"]


def test_detail_limit_defers_instead_of_sending_without_area(monkeypatch, fina):
    """Kandidati iznad ograničenja otvaranja ne vraćaju se (inače bi stigli bez površine),
    nego čekaju sljedeće pokretanje."""
    from scraper.sources import njuskalo, realestatecroatia
    from scraper.sources.base import INCREMENTAL

    page = read("realestatecroatia_kuce.html.gz")

    class Resp:
        def __init__(self, text):
            self.text = text

    class Http:
        def __init__(self):
            self.urls = []

        def get(self, url, **kw):
            self.urls.append(url)
            if "detail.asp" in url:
                return Resp(read("realestatecroatia_oglas.html.gz"))
            return Resp(page if "vrsta=1" in url and "page=1" in url else "")

    monkeypatch.setattr(realestatecroatia, "MAX_DETAILS", 2)
    cfg = load_config()
    src = realestatecroatia.RealEstateCroatia(Http(), Locator(), cfg["kriteriji"])
    first = {x.source_id for x in src.fetch(INCREMENTAL, set())}
    candidates = [x for x in realestatecroatia.parse_list(page, HOUSE) if x.price]
    assert len(first) < len(candidates)                      # neki čekaju
    second = {x.source_id for x in src.fetch(INCREMENTAL, first)}
    assert second - first                                    # sljedeći put dolaze odgođeni
    opened = [x for x in src.fetch(INCREMENTAL, set()) if "opis_skracen" not in x.extra]
    assert opened and all(x.area for x in opened)            # otvoreni imaju površinu

    monkeypatch.setattr(njuskalo, "MAX_DETAILS", 0)
    browser = FakeBrowser({"prodaja-kuca": read("njuskalo_kuce.html.gz"),
                           "prodaja-zemljista": read("njuskalo_zemljista.html.gz")})
    nj = njuskalo.Njuskalo(None, Locator(), cfg["kriteriji"], browser=browser)
    nj.since = "2026-10-05T11:30:00+02:00"
    items = {x.source_id for x in nj.fetch(INCREMENTAL, {"45180000"})}
    assert "51323938" not in items and "45131418" in items  # kandidat čeka; preskup se vraća bez otvaranja
