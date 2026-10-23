"""Parseri na spremljenim stvarnim stranicama (tests/fixtures)."""

import gzip
import json
import re
from pathlib import Path

import pytest

from scraper.locations import Locator
from scraper.models import HOUSE, LAND, Listing
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
    assert x.extra["samo_popis"]                       # bez opisa i vrste dok se oglas ne otvori


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
    assert all(x.area is None or x.area > 0 for x in items.values())       # "0.00" je prazno polje
    assert sum(x.kind == HOUSE for x in items.values()) == 5



def test_njuskalo_list_houses():
    from scraper.sources.njuskalo import parse_list

    items = {x.source_id: x for x in parse_list(read("njuskalo_kuce.html.gz"), HOUSE)}
    assert len(items) == 34 and sum(x.extra["istaknut"] for x in items.values()) == 9   # 3 SuperVau
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


def test_njuskalo_list_includes_super_vau():
    """Plaćeno istaknuti oglasi (SuperVau) su oglasi iste kategorije: čitaju se (bez datuma u
    odluci o sljedećoj stranici); "Latest" (najnoviji s cijelog Njuškala) ne."""
    from scraper.sources.njuskalo import parse_list

    items = {x.source_id: x for x in parse_list(read("njuskalo_kuce.html.gz"), HOUSE)}
    assert {"48499657", "47749175"} <= set(items) and items["48499657"].extra["istaknut"]
    assert "51741047" not in items


def test_njuskalo_detail():
    from scraper.sources.njuskalo import parse_detail, parse_list

    house = next(x for x in parse_list(read("njuskalo_kuce.html.gz"), HOUSE) if x.source_id == "45131418")
    assert house.extra["samo_popis"]
    parse_detail(read("njuskalo_kuca_oglas.html.gz"), house)
    assert house.subtype == "Samostojeća kuća" and house.area == 157 and house.plot_area == 250
    assert "samo_popis" not in house.extra
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

    # Jedan neobičan broj (druga numeracija, pogrešno pročitan) ne čini sve nove oglase starima.
    for known in ({str(45_180_000 - i) for i in range(30)} | {"1051234567"}, {"45180000", "1051234567"}):
        items = {x.source_id: x for x in Njuskalo(None, Locator(), load_config()["kriteriji"], browser=browser)
                 .fetch(INCREMENTAL, known)}
        assert items["41395237"].extra.get("stari_oglas") and items["45131418"].extra.get("stari_oglas") is None

    # 19. 10.: oglas s brojem većim od najvećeg na početku praćenja nije star, i kad se na popisu
    # pojavi danima nakon dobivanja broja (zadnja 3 dana brojeva tada su već daleko iznad njega).
    src = Njuskalo(None, Locator(), load_config()["kriteriji"], browser=browser)
    src.start_max_id = 45_100_000
    items = {x.source_id: x for x in src.fetch(INCREMENTAL, {"45300000"})}
    assert items["41395237"].extra.get("stari_oglas") and items["45131418"].extra.get("stari_oglas") is None


def test_njuskalo_deferred_listing_that_expired_comes_with_warning(fina):
    """Oglas odgođen prošli put, a u međuvremenu istekao ("Ovaj oglas je neaktivan."): stiže
    s upozorenjem (prilika – drugi ga više ne vide), s podacima sa stranice."""
    from scraper.filters import evaluate
    from scraper.models import WARN
    from scraper.sources.base import INCREMENTAL
    from scraper.sources.njuskalo import Njuskalo, parse_list

    expired = read("njuskalo_kuca_oglas.html.gz").replace(
        "<h1", '<div class="ClassifiedDetailUnavailableNotice"><h3>Ovaj oglas je neaktivan.</h3></div><h1', 1)
    browser = FakeBrowser({"prodaja-kuca": read("njuskalo_kuce.html.gz"),
                           "prodaja-zemljista": read("njuskalo_zemljista.html.gz"), "oglas-": expired})
    cfg = load_config()["kriteriji"]
    src = Njuskalo(None, Locator(), cfg, browser=browser)
    src.since = "2026-10-05T11:30:00+02:00"
    waiting = next(x for x in parse_list(read("njuskalo_kuce.html.gz"), HOUSE) if x.source_id == "51323938")
    waiting.source_id, waiting.url = "51000001", waiting.url.replace("51323938", "51000001")
    src.pending = [waiting]
    x = {x.source_id: x for x in src.fetch(INCREMENTAL, {"45180000"})}["51000001"]
    assert x.extra["neaktivan"] and x.plot_area == 250 and "samo_popis" not in x.extra
    d = evaluate(x, cfg, Locator())
    assert d.status == WARN and "oglas je istekao (Njuškalo: neaktivan, nije više na popisu)" in d.warnings


def test_njuskalo_detail_captcha_pauses_without_counting_attempts(fina):
    """Captcha na stranici oglasa (popis radi): oglas se odgađa bez brojanja pokušaja, dva sata
    (captcha_until, pamti runner) se ne otvara nijedan, a oglas odgođen 18 pokretanja zaredom
    stiže s podacima s popisa. Broje se pokretanja, ne sati (noć se ne broji)."""
    from datetime import datetime, timedelta, timezone

    from scraper.sources.base import INCREMENTAL, MAX_DEFERRALS
    from scraper.sources.njuskalo import Njuskalo

    captcha = "<html><title>Captcha</title></html>"
    browser = FakeBrowser({"prodaja-kuca": read("njuskalo_kuce.html.gz"),
                           "prodaja-zemljista": read("njuskalo_zemljista.html.gz"), "oglas-": captcha})
    cfg = load_config()["kriteriji"]

    def run(pending, until=""):
        src = Njuskalo(None, Locator(), cfg, browser=browser)
        src.since, src.pending, src.captcha_until = "2026-10-05T11:30:00+02:00", pending, until
        browser.calls.clear()
        items = {x.source_id: x for x in src.fetch(INCREMENTAL, {"45180000"})}
        return src, items, [u for u in browser.calls if "/nekretnine/" in u]

    src, items, opened = run([])
    assert len(opened) == 1 and src.detail_blocked and not src.detail_ok   # jedna captcha, dalje ništa
    waiting, until = src.deferred, src.captcha_until
    assert waiting and "51323938" not in items and until
    assert all(x.extra.get("pokusaja", 0) == 0 for x in waiting)
    src, items, opened = run(waiting, until)                             # stanka: ne otvara
    assert opened == [] and src.detail_blocked and len(src.deferred) == len(waiting)
    # Stanka predaleko u budućnosti (sat na mobitelu bio je naprijed) ne vrijedi.
    far = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(timespec="seconds")
    src, items, opened = run(src.deferred, far)
    assert len(opened) == 1
    for x in src.deferred:                                               # 18 pokretanja zaredom odgođen
        x.extra["odgodjeno_puta"] = MAX_DEFERRALS
    src, items, opened = run(src.deferred, "2000-01-01T00:00:00+00:00")
    assert len(opened) == 1 and "51323938" in items and items["51323938"].extra.get("samo_popis")


# Zemljišta: popis nije prazan (prazna prva stranica kategorije je greška izvora).
LAND_ITEM = {"code": 9999, "title": "Zemljište", "price": 5_000_000, "summary": {"area": 900},
             "countyName": "Primorsko-goranska", "cityName": "Omišalj", "settlementName": "Njivice", "smartLink": "z"}


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

        if "single-ad" in url:                    # oglasa nema: prazan odgovor
            ad = self.ads.get(url.split("code=")[1].split("&")[0])
            return Resp({"data": [ad] if ad else []})
        if "category=houses-for-sale" in url:
            return Resp({"data": self.items, "nextPage": -1})
        return Resp({"data": [LAND_ITEM], "nextPage": -1})


def index_item(code, price, city="Omišalj", settlement="Njivice"):
    return {"code": code, "title": f"Kuća {settlement}", "price": price, "summary": {"area": 120},
            "countyName": "Primorsko-goranska", "cityName": city, "settlementName": settlement, "smartLink": "k"}


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
    # Otvaraju se samo novi oglasi koji bi mogli proći: ne preskupa kuća, ne izvan područja, ne već
    # poznat. Zemljište na našem području otvara se i kad je preskupo (opis može spominjati parcelaciju).
    assert sorted(u.split("code=")[1].split("&")[0] for u in opened) == ["1", "2", "9999"]
    x1, x2 = found["1"], found["2"]
    assert x1.subtype == "Samostojeća kuća" and x1.plot_area == 400 and x1.extra["parking"] == "vanjsko parkirno mjesto"
    assert x1.extra["godina_izgradnje"] == 1978 and x1.extra["vlasnicki_list"] and "samo_popis" not in x1.extra
    d1 = evaluate(x1, cfg, Locator())
    assert d1.status == WARN and any(w.startswith("suvlasništvo") for w in d1.warnings)
    assert evaluate(x2, cfg, Locator()).status == REJECT  # dvojna kuća iz vrste u oglasu


def test_index_defers_ads_it_cannot_open(monkeypatch):
    """Nov oglas koji pokretanje ne stigne otvoriti (ograničenje, stranica oglasa ne odgovara) ne
    stiže s podacima s popisa – bez vrste bi dvojna kuća prošla – nego čeka sljedeće pokretanje
    (i kad ga popis tada više nema na pročitanim stranicama)."""
    from scraper.filters import evaluate
    from scraper.models import REJECT
    from scraper.sources.base import INCREMENTAL

    monkeypatch.setattr(index_oglasi, "MAX_DETAILS", 2)
    cfg = load_config()["kriteriji"]
    items = [index_item(1, 300_000), index_item(2, 290_000), index_item(3, 280_000)]
    ads = {"1": {"description": "Kuća.", "houseType": 1}, "3": {"description": "Kuća u nizu.", "houseType": 2}}
    src = index_oglasi.IndexOglasi(FakeHttp(items, ads), Locator(), cfg)
    got = {x.source_id for x in src.fetch(INCREMENTAL, set())}
    assert got == {"1"}                                   # 2: stranica prazna; 3 i zemljište: ograničenje
    assert [x.source_id for x in src.deferred] == ["2", "3", "9999"]
    assert src.deferred[0].extra["pokusaja"] == 1

    ads["2"] = {"description": "Kuća.", "houseType": 1}
    later = index_oglasi.IndexOglasi(FakeHttp([index_item(1, 300_000)], ads), Locator(), cfg)   # popis ih više nema
    later.pending = src.deferred
    got = {x.source_id: x for x in later.fetch(INCREMENTAL, {"1"})}
    assert set(got) == {"1", "2", "3"} and got["3"].subtype == "Dvojna kuća"    # 1: poznat, s popisa
    assert evaluate(got["3"], cfg, Locator()).status == REJECT
    assert [x.source_id for x in later.deferred] == ["9999"]


def test_index_reopens_known_ad():
    """Jednokratni popravak: zapamćen oglas (redak iz baze) ponovno se otvara – vrsta s
    oglasa; obrisan oglas → None."""
    from scraper.filters import evaluate
    from scraper.http import FetchError

    def ad(code, category, title, area, **kw):
        return {"code": code, "category": category, "title": title, "price": 250_000, "area": area,
                "countyName": "Primorsko-goranska", "cityName": "Krk", "settlementName": "Krk", "smartLink": "oglas",
                "description": "Prodaje se.", "images": [{"id": 1}], **kw}

    cfg = load_config()["kriteriji"]
    ads = {"7": ad(7, "houses-for-sale", "Kuća u centru grada Krka", 120, houseType=2),
           "8": ad(8, "lands-for-sale", "Zemljište Krk, Pinezići", 900, landType=2)}
    src = index_oglasi.IndexOglasi(FakeHttp([], ads), Locator(), cfg)
    house = src.reopen({"source_id": "7", "kind": HOUSE})
    assert house.kind == HOUSE and house.subtype == "Dvojna kuća" and house.area == 120
    assert house.url == f"{index_oglasi.BASE}/nekretnine/prodaja-kuca/oglas/oglas/7"
    assert "dvojna kuća (vrsta: Dvojna kuća)" in evaluate(house, cfg, Locator()).reasons
    land = src.reopen({"source_id": "8", "kind": LAND})
    assert land.kind == LAND and land.subtype == "Poljoprivredno zemljište"
    assert "nije građevinsko (Poljoprivredno zemljište)" in evaluate(land, cfg, Locator()).reasons
    assert src.reopen({"source_id": "9", "kind": HOUSE}) is None             # prazan odgovor

    class Gone(FakeHttp):
        def get(self, url, **kwargs):
            raise FetchError(f"HTTP 404 za {url}")
    assert index_oglasi.IndexOglasi(Gone([], {}), Locator(), cfg).reopen({"source_id": "7", "kind": HOUSE}) is None


def test_known_ad_with_price_drop_is_opened():
    """Poruka o sniženju poznatog oglasa ne smije imati samo podatke s popisa (oglas iz početnog
    popisa nikad nije otvoren): otvara se i on. Ne čeka: kad se stranica ne da otvoriti, stiže kao
    prije."""
    from scraper.sources.base import INCREMENTAL

    cfg = load_config()["kriteriji"]
    items = [index_item(5, 250_000), index_item(6, 280_000), index_item(7, 260_000)]
    http = FakeHttp(items, {"5": {"description": "Kuća.", "houseType": 2}})
    src = index_oglasi.IndexOglasi(http, Locator(), cfg)
    src.known_prices = {"5": 300_000, "6": 280_000, "7": 300_000}
    got = {x.source_id: x for x in src.fetch(INCREMENTAL, {"5", "6", "7", "9999"})}
    opened = sorted(u.split("code=")[1].split("&")[0] for u in http.calls if "single-ad" in u)
    assert opened == ["5", "7"]                       # 6: ista cijena; 7: stranica prazna
    assert got["5"].subtype == "Dvojna kuća" and got["7"].extra.get("samo_popis") and not src.deferred


def test_new_ad_goes_before_known_price_drop(monkeypatch):
    """Jedno mjesto za otvaranje: dobiva ga nov oglas (zemljište 9999), a poznat oglas sa
    sniženjem stiže s podacima s popisa (ne čeka)."""
    from scraper.sources.base import INCREMENTAL

    monkeypatch.setattr(index_oglasi, "MAX_DETAILS", 1)
    http = FakeHttp([index_item(5, 250_000)], {"5": {"description": "Kuća.", "houseType": 1},
                                               "9999": {"description": "Građevinsko zemljište.", "landType": 1}})
    src = index_oglasi.IndexOglasi(http, Locator(), load_config()["kriteriji"])
    src.known_prices = {"5": 300_000}
    got = {x.source_id: x for x in src.fetch(INCREMENTAL, {"5"})}
    assert [u.split("code=")[1].split("&")[0] for u in http.calls if "single-ad" in u] == ["9999"]
    assert got["5"].extra.get("samo_popis") and not src.deferred


def test_index_renewed_old_ad_is_not_new(monkeypatch):
    """Agencije obnavljaju i oglase stare godinama (13. 10.: 383 odjednom); početni popis ih nije
    pročitao (najviše 80 stranica). Nepoznat oglas objavljen prije početka praćenja bilježi se bez
    poruke (stari_oglas) i otvara se tek nakon novih."""
    from scraper.sources.base import INCREMENTAL

    monkeypatch.setattr(index_oglasi, "MAX_DETAILS", 1)
    old, new = index_item(1, 300_000), index_item(2, 290_000)
    old["postedTime"], new["postedTime"] = "2021-03-01T10:00:00Z", "2026-10-13T06:00:00Z"
    http = FakeHttp([old, new], {"1": {"description": "Kuća.", "houseType": 1}, "2": {"description": "Kuća.", "houseType": 1}})
    src = index_oglasi.IndexOglasi(http, Locator(), load_config()["kriteriji"])
    src.baseline_at = "2026-10-04T16:58:25+02:00"
    src.fetch(INCREMENTAL, {"9999"})
    assert [u.split("code=")[1].split("&")[0] for u in http.calls if "single-ad" in u] == ["2"]
    waiting = {x.source_id: x for x in src.deferred}
    assert waiting["1"].extra.get("stari_oglas") and "stari_oglas" not in new

    # 19. 10.: obnova mijenja i postedTime – star je i oglas s brojem do najvećeg na početku praćenja.
    renewed, fresh = index_item(5, 300_000), index_item(9, 290_000)
    renewed["postedTime"] = fresh["postedTime"] = "2026-10-18T06:00:00Z"
    http = FakeHttp([renewed, fresh], {"5": {"description": "Kuća.", "houseType": 1}, "9": {"description": "Kuća.", "houseType": 1}})
    src = index_oglasi.IndexOglasi(http, Locator(), load_config()["kriteriji"])
    src.baseline_at, src.start_max_id = "2026-10-04T16:58:25+02:00", 7
    found = {x.source_id: x for x in src.fetch(INCREMENTAL, {"9999"}) + src.deferred}
    assert found["5"].extra.get("stari_oglas") and "stari_oglas" not in found["9"].extra


def test_realestatecroatia_detail_and_reopen():
    """realestatecroatia.com: broj parkirnih mjesta sa stranice oglasa; jednokratno ponovno
    otvaranje zapamćenog oglasa (vrsta i mjesto iz zaglavlja stranice) i otvaranje poznatog
    oglasa sa sniženom cijenom (početni popis nije otvarao oglase – bez površine)."""
    from types import SimpleNamespace

    from scraper.filters import evaluate
    from scraper.sources import realestatecroatia as rc
    from scraper.sources.base import INCREMENTAL

    detail, page = read("realestatecroatia_oglas.html.gz"), read("realestatecroatia_kuce.html.gz")

    class Http:
        def __init__(self):
            self.urls = []

        def get(self, url, **kw):
            self.urls.append(url)
            if "detail.asp" in url:
                return SimpleNamespace(text=detail)
            return SimpleNamespace(text=page if url.endswith("page=1") else "")

    cfg = load_config()["kriteriji"]
    src = rc.RealEstateCroatia(Http(), Locator(), cfg)
    row = {"source_id": "1311438", "url": f"{rc.BASE}detail.asp?id=1311438", "title": "Kuća Malinska",
           "kind": HOUSE, "price": 399_000}
    x = src.reopen(row)
    assert (x.subtype, x.settlement, x.area, x.plot_area, x.extra["parking"]) == ("Kuća", "Malinska", 86, 170, "3")
    assert "opis_skracen" not in x.extra
    assert evaluate(x, cfg, Locator()).jls == "Malinska-Dubašnica"

    listed = [y for y in rc.parse_list(page, HOUSE) if y.price]
    known = {y.source_id for y in listed}
    http = Http()
    src = rc.RealEstateCroatia(http, Locator(), cfg)
    drop = next(y for y in listed if src.worth_detail(y))
    src.known_prices = {y.source_id: y.price for y in listed}
    src.known_prices[drop.source_id] = drop.price + 20_000                    # bio je skuplji
    got = {y.source_id: y for y in src.fetch(INCREMENTAL, known)}
    assert [u for u in http.urls if "detail.asp" in u] == [drop.url]
    assert got[drop.source_id].area == 86 and got[drop.source_id].extra["parking"] == "3"


def test_portal_fields_vender_oglasnik_nekretnine():
    """Polja koja portali daju, a nisu u opisu: vrsta kuće iz dodatnih značajki (vender), godine,
    parking, dozvole, vlasnički list, bazen, stanje, okućnica."""
    from scraper.filters import evaluate
    from scraper.models import REJECT
    from scraper.sources import nekretnine_hr, oglasnik, vender

    cfg = load_config()["kriteriji"]
    features = ('a:4:{i:0;a:2:{s:29:"fave_additional_feature_title";s:9:"Tip kuće";s:29:"fave_additional_feature_value";'
                's:6:"dvojna";}i:1;a:2:{s:29:"fave_additional_feature_title";s:24:"Godina zadnje adaptacije";'
                's:29:"fave_additional_feature_value";s:4:"2019";}i:2;a:2:{s:29:"fave_additional_feature_title";'
                's:15:"Parkirna mjesta";s:29:"fave_additional_feature_value";s:1:"2";}i:3;a:2:{s:29:'
                '"fave_additional_feature_title";s:17:"Površina parcele";s:29:"fave_additional_feature_value";'
                's:6:"420 m²";}}')
    item = {"id": 1, "link": "https://vender.hr/1", "title": {"rendered": "Kuća Njivice"}, "property_type": [62],
            "content": {"rendered": "Kuća."}, "property_meta": {
                "fave_property_price": ["300000"], "fave_property_size": ["120"], "fave_property_year": ["1985"],
                "fave_property_price_prefix": ["Stara cijena: 320000"], "additional_features": [features]},
            "_embedded": {"wp:term": [[{"taxonomy": "property_city", "name": "OMIŠALJ"},
                                       {"taxonomy": "property_area", "name": "NJIVICE"},
                                       {"taxonomy": "property_feature", "name": "Bazen"}]]}}
    x = vender.parse_items([item])[0]
    assert x.subtype == "Kuća (dvojna)" and x.plot_area == 420 and x.previous_price == 320_000
    assert (x.extra["godina_izgradnje"], x.extra["godina_obnove"], x.extra["parking"], x.extra["bazen"]) == (1985, 2019, "2", True)
    assert evaluate(x, cfg, Locator()).status == REJECT

    houses = {x.source_id: x for x in oglasnik.parse_page(read("oglasnik_kuce.html.gz"), HOUSE)}
    assert sum(1 for x in houses.values() if x.extra.get("bazen")) == 29
    assert sum(1 for x in houses.values() if x.extra.get("godina_izgradnje")) == 67
    assert any(x.extra.get("dozvole") == ["građevinska dozvola", "uporabna dozvola"] for x in houses.values())
    assert any(x.extra.get("parking") == "samostojeća garaža" for x in houses.values())

    listed = {x.source_id: x for x in nekretnine_hr.parse_page(read("nekretnine_kuce_pgz.html.gz"), HOUSE)[0]}
    assert listed["2627689"].extra["stanje"] == "za renoviranje" and listed["3846159"].extra["bazen"]
    assert listed["3273189"].extra["parking"] == "7" and listed["2509191"].extra["parking"] == "garaža: 1, parkirnih mjesta: 2"
    assert listed["3735293"].extra["stanje"] == "odlično / renovirano"
    detail = {"props": {"pageProps": {"detailData": {"realEstate": {"properties": [{
        "description": "Kuća za obnovu.", "garage": "3 na zajedničkom parkingu", "condition": "Za renoviranje",
        "features": ["Konoba", "bazen"], "primaryFeatures": [{"name": "bazen", "codeName": "pool", "value": 0}],
        "surfaceConstitution": {"surfaceConstitutionElements": [
            {"constitutionKey": "residence", "surface": "80,0 m²"}, {"constitutionKey": "garden", "surface": "1.755,0 m²"}]}}]}}}}}
    y = Listing("nekretnine_hr", "9", "u", "Kuća", HOUSE)
    nekretnine_hr.parse_detail(f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(detail)}</script>', y)
    assert (y.extra["parking"], y.extra["stanje"], y.extra["bazen"], y.plot_area) == (
        "3 na zajedničkom parkingu", "Za renoviranje", True, 1755)


def test_portal_fields_realestatecroatia_and_njuskalo():
    from scraper.sources import njuskalo, realestatecroatia as rc

    page = read("realestatecroatia_oglas.html.gz")
    for old, new, expected in (("Broj parkirnih mjesta:", "Garaža:", "garaža: 3"),
                               ("Broj parkirnih mjesta:</td>\n          <td ><strong>3", "Parkiralište:</td>\n          <td ><strong>48 m2", "parkiralište 48 m²")):
        x = Listing("realestatecroatia", "1", "u", "Kuća", HOUSE)
        rc.parse_detail(page.replace(old, new), x)
        assert x.extra["parking"] == expected, expected

    groups = ('<h3 class="ClassifiedDetailPropertyGroups-groupTitle">Dozvole</h3><ul>'
              '<li class="ClassifiedDetailPropertyGroups-groupListItem">Vlasnički list</li>'
              '<li class="ClassifiedDetailPropertyGroups-groupListItem">Građevinska dozvola</li>'
              '<li class="ClassifiedDetailPropertyGroups-groupListItem">Uporabna dozvola</li></ul>'
              '<h3 class="ClassifiedDetailPropertyGroups-groupTitle">Ostali objekti i površine</h3><ul>'
              '<li class="ClassifiedDetailPropertyGroups-groupListItem">Bazen</li></ul>')
    renovated = ('<dt class="ClassifiedDetailBasicDetails-listTerm">Godina zadnje renovacije</dt>\n'
                 '<dd class="ClassifiedDetailBasicDetails-listDefinition">2018.</dd>')
    detail = read("njuskalo_kuca_oglas.html.gz")
    detail = detail.replace('<dt class="ClassifiedDetailBasicDetails-listTerm">', renovated + '<dt class="ClassifiedDetailBasicDetails-listTerm">', 1)
    detail = detail.replace('<h3 class="ClassifiedDetailPropertyGroups-groupTitle">', groups + '<h3 class="ClassifiedDetailPropertyGroups-groupTitle">', 1)
    x = Listing("njuskalo", "1", "u", "Kuća", HOUSE)
    njuskalo.parse_detail(detail, x)
    assert (x.extra["bazen"], x.extra["vlasnicki_list"], x.extra["dozvole"], x.extra["godina_obnove"]) == (
        True, True, ["građevinska dozvola", "uporabna dozvola"], 2018)
    assert x.extra["prikljucci"] == ["voda"]                 # "Gradski vodovod" (grupa "Podaci o objektu")
    # "Bazen: Ne" nije bazen (fold() briše dvotočku – nijekanje se traži na kraju).
    y = Listing("njuskalo", "2", "u", "Kuća", HOUSE)
    njuskalo.parse_detail(detail.replace(">Bazen<", ">Bazen: Ne<").replace(">Vlasnički list<", ">Vlasnički list: Ne<"), y)
    assert "bazen" not in y.extra and "vlasnicki_list" not in y.extra


def test_njuskalo_opens_known_ad_with_price_drop_or_without_area(fina):
    """Njuškalo: poznat oglas se otvara kad mu je cijena snižena ili je zapamćen bez površine
    (stari ponovno objavljen, početni popis); bez sniženja ne."""
    from scraper.sources.base import INCREMENTAL
    from scraper.sources.njuskalo import Njuskalo, parse_list

    # Svi oglasi s popisa su poznati (novi bi imali prednost i popunili mjesta za otvaranje).
    known = {x.source_id for page, kind in (("njuskalo_kuce.html.gz", HOUSE), ("njuskalo_zemljista.html.gz", LAND))
             for x in parse_list(read(page), kind)}

    def run(prices, incomplete=()):
        browser = FakeBrowser({"prodaja-kuca": read("njuskalo_kuce.html.gz"),
                               "prodaja-zemljista": read("njuskalo_zemljista.html.gz"),
                               "oglas-51323938": read("njuskalo_kuca_oglas.html.gz")})
        src = Njuskalo(None, Locator(), load_config()["kriteriji"], browser=browser)
        src.since, src.known_prices, src.known_incomplete = "2026-10-05T11:30:00+02:00", prices, set(incomplete)
        items = {x.source_id: x for x in src.fetch(INCREMENTAL, known)}
        return items["51323938"], [u for u in browser.calls if "oglas-51323938" in u], src.deferred

    x, opened, deferred = run({"51323938": 368_000})
    assert not opened and "detalji" not in x.extra
    x, opened, deferred = run({"51323938": 400_000})
    assert opened and x.extra.get("detalji") and x.plot_area == 250
    assert "51323938" not in {y.source_id for y in deferred}           # poznat oglas ne čeka
    x, opened, _ = run({"51323938": 368_000}, {"51323938"})
    assert opened and x.extra.get("detalji")


def test_reopen_vender_oglasnik_nekretnine():
    """Jednokratno ponovno otvaranje zapamćenih oglasa (nova polja): vender (API jednog oglasa),
    oglasnik (stranica oglasa ima i druge oglase), nekretnine.hr (podaci stranice oglasa)."""
    from types import SimpleNamespace

    from scraper.http import FetchError
    from scraper.sources import nekretnine_hr, oglasnik, vender

    cfg = load_config()["kriteriji"]
    item = {"id": 7, "link": "https://vender.hr/7", "title": {"rendered": "Kuća Njivice"}, "property_type": [19277],
            "content": {"rendered": "Kuća."}, "property_meta": {"fave_property_price": ["300000"], "fave_property_size": ["120"]},
            "_embedded": {"wp:term": [[{"taxonomy": "property_city", "name": "OMIŠALJ"},
                                       {"taxonomy": "property_feature", "name": "Garaža"}]]}}
    ogl = read("oglasnik_kuce.html.gz")
    detail = {"realEstate": {"id": 9, "title": "Kuća Njivice", "price": {"visible": True, "value": 300_000}, "properties": [{
        "surface": "120 m²", "typology": {"name": "Kuća"}, "description": "Kuća u mirnom dijelu.", "condition": "Za renoviranje",
        "location": {"city": "Omišalj", "macrozone": "Njivice", "province": "Primorsko-goranska"}}]}}
    nek = '<script id="__NEXT_DATA__" type="application/json">' + json.dumps({"props": {"pageProps": {"detailData": detail}}}) + "</script>"

    class Http:
        def get(self, url, **kw):
            if "properties/7" in url:
                return SimpleNamespace(json=lambda: item)
            if "oglas-404" in url or "properties/8" in url:
                raise FetchError(f"HTTP 404 za {url}")
            return SimpleNamespace(text=ogl if "oglasnik" in url else nek)

    x = vender.Vender(Http(), Locator(), cfg).reopen({"source_id": "7", "kind": HOUSE})
    assert x.subtype == "Samostojeća kuća" and x.extra["parking"] == "garaža"
    assert vender.Vender(Http(), Locator(), cfg).reopen({"source_id": "8", "kind": HOUSE}) is None
    first = oglasnik.parse_page(ogl, HOUSE)[3]
    src = oglasnik.Oglasnik(Http(), Locator(), cfg)
    got = src.reopen({"source_id": first.source_id, "url": "https://oglasnik.hr/kuce-prodaja/x-oglas-1", "kind": HOUSE})
    assert got.source_id == first.source_id and got.extra == first.extra
    assert src.reopen({"source_id": "1", "url": "https://oglasnik.hr/kuce-prodaja/x-oglas-1", "kind": HOUSE}) is None
    assert src.reopen({"source_id": "1", "url": "https://oglasnik.hr/oglas-404", "kind": HOUSE}) is None
    y = nekretnine_hr.NekretnineHr(Http(), Locator(), cfg).reopen({"source_id": "9", "url": "https://www.nekretnine.hr/oglasi/9/", "kind": HOUSE})
    assert (y.source_id, y.area, y.settlement, y.extra["stanje"]) == ("9", 120, "Njivice", "Za renoviranje")
    assert "opis_skracen" not in y.extra


def test_oglasnik_ad_page_format():
    """Stranica oglasa (ponovno otvaranje) zapisuje cijenu kao broj, a slike drukčije nego popis
    (12. 10. na GitHubu: AttributeError 'int' object has no attribute 'get')."""
    from scraper.sources.oglasnik import _listing

    ad = {"id": 7080680, "title": "Kuća Njivice", "price": 160000, "media": "", "publishedAt": 1791868578000,
          "category": {"id": 238, "url": "kuce-prodaja"},
          "location": [{"name": "Hrvatska"}, {"name": "Primorsko-goranska"}, {"name": "Omišalj"}, {"name": "Njivice"}],
          "details": [{"group": "Osnovni podaci", "params": [
              {"slug": "re_house_type", "value": "samostojeća kuća"}, {"slug": "re_living_area", "value": "135"},
              {"slug": "re_house_infield", "value": "bazen"}, {"slug": "re_permits", "value": "vlasnički list"}]}]}
    x = _listing(ad, HOUSE, {}, {})
    assert (x.price, x.area, x.settlement, x.image_url, x.extra["bazen"], x.extra["vlasnicki_list"]) == (
        160000, 135, "Njivice", "", True, True)


def test_land_utilities_from_portal_fields():
    """Priključci zemljišta iz polja: index.hr (voda, kanalizacija, asfalt), vender (oznake; i
    vlasnički list, dozvole), nekretnine.hr (popis na talijanskom, stranica oglasa; vrijednost 0 =
    nema), pristup."""
    from scraper.notify import format_listing
    from scraper.filters import evaluate
    from scraper.sources import nekretnine_hr, vender

    cfg = load_config()["kriteriji"]
    x = Listing("index_oglasi", "1", "u", "Zemljište Njivice", LAND, area=800, price=150_000)
    index_oglasi.parse_single({"data": [{"description": "Zemljište.", "landType": 1, "cityWaterSupply": True,
                                         "asphaltRoad": True, "citySewerage": True}]}, x)
    assert x.extra["prikljucci"] == ["voda", "kanalizacija", "asfaltni put"]

    item = {"id": 5, "link": "https://vender.hr/5", "title": {"rendered": "Zemljište Njivice"}, "property_type": [19276],
            "content": {"rendered": "Zemljište."}, "property_meta": {"fave_property_price": ["150000"], "fave_property_land": ["800"]},
            "_embedded": {"wp:term": [[{"taxonomy": "property_city", "name": "OMIŠALJ"},
                                       *({"taxonomy": "property_feature", "name": n} for n in (
                                           "Struja", "Gradski vodovod", "Asfaltni put", "Vlasnički list", "Građevinska dozvola",
                                           "Pogled na more"))]]}}
    y = vender.parse_items([item])[0]
    assert (y.extra["prikljucci"], y.extra["vlasnicki_list"], y.extra["dozvole"]) == (
        ["struja", "voda", "asfaltni put"], True, ["građevinska dozvola"])

    listed = {z.source_id: z for z in nekretnine_hr.parse_page(read("nekretnine_zemljista_pgz.html.gz"), LAND)[0]}
    assert any(z.extra.get("prikljucci") == ["struja", "voda", "kanalizacija"] for z in listed.values())
    detail = {"props": {"pageProps": {"detailData": {"realEstate": {"properties": [{
        "description": "Građevinsko zemljište.", "features": ["Priključak za vodu", "orijentacija zapad"],
        "primaryFeatures": [{"name": "Priključak za struju", "value": 1}, {"name": "Plinski priključak", "value": 0}],
        "land": {"access": "Na makadamskoj cesti"}}]}}}}}
    z = Listing("nekretnine_hr", "9", "u", "Zemljište Njivice", LAND, price=150_000, area=800,
                county="Primorsko-goranska", municipality="Omišalj", settlement="Njivice")
    nekretnine_hr.parse_detail(f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(detail)}</script>', z)
    assert (z.extra["prikljucci"], z.extra["pristup"], z.plot_area) == (["struja", "voda"], "Na makadamskoj cesti", None)
    text = format_listing(z, evaluate(z, cfg, Locator()))
    assert "🔌 priključci: struja ✔ · voda ✔ · pristup: na makadamskoj cesti" in text


def test_nekretnine_defers_ads_it_cannot_open(monkeypatch):
    """nekretnine.hr: stranica oglasa ne odgovara → oglas čeka sljedeće pokretanje (puni opis)."""
    from types import SimpleNamespace

    from scraper.sources.base import INCREMENTAL

    def fake_parse(text, kind):
        if kind != HOUSE or "pag=1" not in text:
            return [], 1
        return [Listing(source="nekretnine_hr", source_id="1", url="https://x/1", title="Kuća Njivice", kind=HOUSE,
                        subtype="Samostojeća kuća", price=300_000, area=120, county="Primorsko-goranska",
                        municipality="Omišalj", settlement="Njivice")], 1

    class Http:
        def get(self, url, **kw):
            if url == "https://x/1":
                raise TimeoutError("stranica oglasa ne odgovara")
            return SimpleNamespace(text=url)

    monkeypatch.setattr(nekretnine_hr, "parse_page", fake_parse)
    src = nekretnine_hr.NekretnineHr(Http(), Locator(), load_config()["kriteriji"])
    assert src.fetch(INCREMENTAL, set()) == [] and [x.source_id for x in src.deferred] == ["1"]


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
            return Resp(page if "page=1&" in url + "&" or "vrsta=1" in url else "")   # zemljišta: isti popis

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
    assert burza._areas("Moguća gradnja kuće 150 m2 na zemljištu 800 m2", LAND) == (800, None)   # zemljište: najveća

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
            return Resp(page if ("kuce" in url and "crikvenica" in url) or url.endswith("kvarner-i-istra") else "")

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


BURZA_FEATURES = """<html><h5>Lokacija:</h5><span class="place-name">Cizici</span>
<div class="bad-features"><table class="table"><tbody>
<th>Godina izgradnje</th><td>1975</td></tr>
<th>Kvadratura</th><td>1334 m<sup>2</sup></td></tr>
<tr><td colspan="2"><h6>Vrsta zemljišta</h6><ul><li>Građevinsko zemljište</li></ul></td></tr>
<tr><td colspan="2"><h6>Pristupni put</h6><ul><li>Asfaltni put</li></ul></td></tr>
<tr><td colspan="2"><h6>Priključci</h6><ul><li>Struja</li><li>Voda</li><li>Kanalizacija</li><li>Internet</li></ul></td></tr>
<tr><td colspan="2"><h6>Prateći objekti</h6><ul><li>Garaža</li><li>Podrum</li></ul></td></tr>
<tr><td colspan="2"><h6>Opremljenost i sadržaji</h6><ul><li>Bazen</li></ul></td></tr>
<tr><td colspan="2"><h6>U blizini</h6><ul><li>More</li></ul></td></tr>
</tbody></table></div><!-- .bad-features -->
<div class="bad-text"><hr><h5>Opis:</h5><p>Prodajem gradilište 430 m2, centar naselja.</p></div>
<div>Zadnja izmjena: <strong>23.10.2026.</strong></div></html>"""


def test_burza_detail_reads_feature_table():
    """Korisnik 23. 10. (burza 351078): stranica oglasa ima tablicu – priključci, pristupni put,
    vrsta zemljišta – a poruka ih nije imala (⚠ "vrsta zemljišta nije navedena")."""
    from scraper import prikljucci
    from scraper.filters import evaluate
    from scraper.models import Listing
    from scraper.sources import burza

    x = Listing("burza", "351078", "https://burza.com.hr/oglasi/gradiliste/351078", "Gradilište otok Krk, Čižići",
                LAND, price=160_000)
    burza.parse_detail(BURZA_FEATURES, x)
    assert (x.subtype, x.area, x.settlement) == ("Građevinsko zemljište", 1334, "Cizici")   # kvadratura, ne tekst
    assert x.extra["prikljucci"] == ["struja", "voda", "kanalizacija", "internet"]
    assert x.extra["pristup"] == "Asfaltni put" and x.extra["godina_izgradnje"] == 1975
    assert x.extra["parking"] == "garaža" and x.extra["bazen"]
    assert prikljucci.check(x) == "🔌 priključci: struja ✔ · voda ✔ · kanalizacija ✔ · internet ✔ · pristup: asfaltni put"
    cfg = load_config()["kriteriji"]
    assert "vrsta zemljišta nije navedena" not in evaluate(x, cfg, Locator(), None).warnings

    house = Listing("burza", "2", "https://burza.com.hr/oglasi/kuca/2", "Kuća Matulji", HOUSE, price=300_000)
    burza.parse_detail(BURZA_FEATURES.replace("<th>Godina izgradnje</th><td>1975</td>",
                                              "<th>Vrsta kuće</th><td>Dvojna kuća</td>"), house)
    assert house.subtype == "Dvojna kuća" and "godina_izgradnje" not in house.extra
    assert any(r.startswith("dvojna kuća (vrsta") for r in evaluate(house, cfg, Locator(), None).reasons)

    plain = Listing("burza", "3", "https://burza.com.hr/oglasi/x/3", "Zemljište", LAND, price=100_000)
    burza.parse_detail('<h5>Lokacija:</h5><span class="place-name">Krk</span>'
                       '<div class="bad-text"><p>Zemljište 600 m2.</p></div>', plain)
    assert (plain.subtype, plain.area) == ("", 600) and "prikljucci" not in plain.extra   # bez tablice: kao prije


def test_burza_house_fields_from_table():
    """Revizija 23. 10.: kvadratura kuće i okućnice, broj parkirnih mjesta, zadnja adaptacija, stanje
    ("Starina" → za obnovu), pravni status pristupa, čisto vlasništvo."""
    from scraper import parking
    from scraper.filters import evaluate
    from scraper.models import Listing
    from scraper.sources import burza

    page = """<h5>Lokacija:</h5><span class="place-name">Dramalj</span>
<div class="bad-features"><table class="table"><tbody>
<th>Vrsta kuće</th><td>Samostojeća kuća</td></tr><th>Kvadratura kuće</th><td>190</td></tr>
<th>Kvadratura okućnice</th><td>477</td></tr><th>Broj parkirnih mjesta</th><td>2</td></tr>
<th>Zadnja adaptacija</th><td>2015</td></tr><th>Stanje nekretnine</th><td>Starina</td></tr>
<th>Pravni status pristupa</th><td>Pravo služnosti</td></tr>
<tr><td colspan="2"><h6>Pristupni put</h6><ul><li>Asfaltni put</li></ul></td></tr>
<tr><td colspan="2"><h6>Prateći objekti</h6><ul><li>Garaža</li></ul></td></tr>
<tr><td colspan="2"><h6>Opremljenost i sadržaji</h6><ul><li>Čisto vlasništvo</li></ul></td></tr>
</tbody></table></div><div class="bad-text"><p>Kuća 250 m2 na okućnici 600 m2.</p></div>"""
    x = Listing("burza", "1", "https://burza.com.hr/oglasi/k/1", "Kuća Dramalj", HOUSE, price=280_000)
    burza.parse_detail(page, x)
    assert (x.subtype, x.area, x.plot_area) == ("Samostojeća kuća", 190, 477)     # polja, ne tekst
    assert x.extra["parking"] == "garaža, parkirnih mjesta: 2" and x.extra["godina_obnove"] == 2015
    assert x.extra["pristup"] == "Asfaltni put (pravo služnosti)" and x.extra["vlasnicki_list"]
    assert x.extra["stanje"] == "starina"
    evaluate(x, load_config()["kriteriji"], Locator(), None)
    assert x.extra["za_obnovu"] and parking.check(x)[0] == "🚗 garaža, parkirnih mjesta: 2"
    only = Listing("burza", "2", "u", "Kuća", HOUSE, price=1)
    burza.parse_detail(page.replace("<li>Garaža</li>", "<li>Spremište</li>"), only)
    assert only.extra["parking"] == "2"                                   # "🚗 parkirnih mjesta: 2"


def test_gradiliste_is_building_land():
    """"Gradilište" u naslovu je građevinska čestica; "u blizini gradilišta" ne čini poljoprivredno građevinskim."""
    from scraper.filters import evaluate
    from scraper.models import Listing

    cfg = load_config()["kriteriji"]
    plot = Listing("index_oglasi", "1", "u", "Gradilište Čižići 430 m2", LAND, price=160_000, area=430,
                   municipality="Dobrinj", settlement="Čižići", description="Prodaje se, pogled na more.")
    assert "vrsta zemljišta nije navedena" not in evaluate(plot, cfg, Locator(), None).warnings
    farm = Listing("index_oglasi", "2", "u", "Poljoprivredno zemljište Čižići", LAND, price=60_000, area=900,
                   municipality="Dobrinj", settlement="Čižići", description="U blizini gradilišta nove ceste.")
    assert "nije građevinsko (naslov)" in evaluate(farm, cfg, Locator(), None).reasons


def test_burza_reopen_reads_page_and_missing_listing():
    from scraper.http import FetchError
    from scraper.sources import burza

    class Http:
        def get(self, url, **kw):
            if url.endswith("/404"):
                raise FetchError(f"HTTP 404 za {url}")
            return type("R", (), {"text": BURZA_FEATURES})()

    src = burza.Burza(Http(), Locator(), load_config()["kriteriji"])
    assert src.reopen_once
    row = {"source_id": "351078", "url": "https://burza.com.hr/oglasi/g/351078", "title": "Gradilište", "kind": LAND,
           "price": 160_000}
    x = src.reopen(row)
    assert x.subtype == "Građevinsko zemljište" and x.extra["samo_pgz"] and "opis_skracen" not in x.extra
    assert src.reopen({**row, "url": "https://burza.com.hr/oglasi/g/404"}) is None


def test_burza_opens_known_listing_with_lower_price():
    """15. 10. (kao realestatecroatia 989420, gdje je "dvojna kuća" bila samo u punom opisu): poznat
    oglas sa sniženom cijenom otvara se, da poruka o sniženju ima pun opis; ostali poznati ne."""
    from scraper.sources import burza

    page = read("burza_kuce.html.gz")
    prices = {x.source_id: x.price for x in burza.parse_list(page, HOUSE, "Crikvenica")}

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
            return Resp(page if url.endswith("kvarner-i-istra") else "")

    http = Http()
    src = burza.Burza(http, Locator(), load_config()["kriteriji"])
    src.known_prices = {"350166": prices["350166"] + 10_000, "350164": prices["350164"]}
    found = {x.source_id: x for x in src.fetch("incremental", {"350166", "350164"})}
    assert sorted(u.split("/")[-1] for u in http.urls if u.split("/")[-1].isdigit()) == ["347113", "350118", "350166"]
    assert found["350166"].description.startswith("Prodaje se velika") and "opis_skracen" not in found["350166"].extra
    assert found["350164"].extra["opis_skracen"]                      # ista cijena: bez otvaranja


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
            return Resp(page if url.endswith("page=1") else "")      # zemljišta: isti popis

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
    assert "51323938" in {x.source_id for x in nj.deferred}

    # Sljedeće pokretanje: oglasa više nema na pročitanim stranicama (novi su ga pomaknuli),
    # ali se otvara jer je zapamćen kao odgođen.
    monkeypatch.setattr(njuskalo, "MAX_DETAILS", 8)
    later = njuskalo.Njuskalo(None, Locator(), cfg["kriteriji"], browser=FakeBrowser({
        "prodaja-kuca": read("njuskalo_zemljista.html.gz"), "prodaja-zemljista": read("njuskalo_zemljista.html.gz"),
        "oglas-51323938": read("njuskalo_kuca_oglas.html.gz")}))
    later.since, later.pending = nj.since, nj.deferred
    got = {x.source_id: x for x in later.fetch(INCREMENTAL, {"45180000"})}
    assert got["51323938"].extra.get("detalji") and got["51323938"].area


def test_deferred_detail_gives_up_after_three_failures():
    """Stranica oglasa ne odgovara: pokušava se još dva puta, zatim oglas stiže s podacima s popisa."""
    from scraper.models import Listing
    from scraper.sources.base import Source

    src = Source(None, None, {})
    x = Listing("t", "1", "u", "Kuća", HOUSE)
    assert src.defer(x) and x.extra.get("pokusaja", 0) == 0          # ograničenje otvaranja: bez brojanja
    assert src.defer(x, failed=True) and src.defer(x, failed=True)
    assert not src.defer(x, failed=True)
    src.pending = [x]
    found = {}
    src.add_pending(found, set())
    assert found["1"].extra["pokusaja"] == 3
    found = {}
    src.add_pending(found, {"1"})                                    # u međuvremenu poznat → ne otvara se ponovno
    assert found == {}


def test_index_reads_more_pages_while_new(fina):
    """Redovno: index.hr čita sljedeću stranicu dok ima novih oglasa (ujutro ih je više)."""
    from scraper.sources.base import INCREMENTAL

    def item(code):
        return {"code": code, "title": "Kuća Njivice", "price": 900_000, "summary": {"area": 120},
                "countyName": "Primorsko-goranska", "cityName": "Omišalj", "settlementName": "Njivice", "smartLink": "k"}

    class Paged(FakeHttp):
        def get(self, url, **kwargs):
            self.calls.append(url)
            page = int(url.split("&page=")[1].split("&")[0]) if "&page=" in url else 1

            class Resp:
                def __init__(self, data):
                    self.data = data

                def json(self):
                    return self.data
            if "houses-for-sale" in url:
                return Resp({"data": [item(page * 100 + i) for i in range(24)], "nextPage": page + 1})
            return Resp({"data": [LAND_ITEM], "nextPage": -1})

    http = Paged([], {})
    src = index_oglasi.IndexOglasi(http, Locator(), load_config()["kriteriji"])
    known = {str(300 + i) for i in range(24)}                    # 3. stranica već poznata
    src.fetch(INCREMENTAL, known)
    assert sum("houses-for-sale" in u for u in http.calls) == 3


def test_index_reads_on_while_page_is_recent(fina):
    """Popis je poredan po zadnjoj aktivnosti: stranica puna obnovljenih (poznatih) oglasa
    nakon prošlog čitanja ne zaustavlja čitanje – nov oglas može biti na sljedećoj."""
    from scraper.sources.base import INCREMENTAL

    def item(code, when, promoted=False):
        return {"code": code, "title": "Kuća Njivice", "price": 900_000, "summary": {"area": 120}, "isPromoted": promoted,
                "countyName": "Primorsko-goranska", "cityName": "Omišalj", "settlementName": "Njivice", "smartLink": "k",
                "postedTime": "2026-08-01T10:00:00Z", "renewalTime": when}

    pages = {1: [item(100 + i, "2026-10-06T05:30:00Z") for i in range(24)],         # obnovljeni noću
             2: [item(200, "2026-10-06T05:00:00Z")] + [item(201 + i, "2026-10-05T19:00:00Z") for i in range(23)],
             3: [item(300 + i, "2026-10-05T10:00:00Z") for i in range(24)]}

    class Paged(FakeHttp):
        def get(self, url, **kwargs):
            self.calls.append(url)
            page = int(url.split("&page=")[1].split("&")[0]) if "&page=" in url else 1

            class Resp:
                def __init__(self, data):
                    self.data = data

                def json(self):
                    return self.data
            if "houses-for-sale" in url:
                return Resp({"data": pages.get(page, []), "nextPage": page + 1})
            return Resp({"data": [LAND_ITEM], "nextPage": -1})

    http = Paged([], {})
    src = index_oglasi.IndexOglasi(http, Locator(), load_config()["kriteriji"])
    src.since = "2026-10-05T22:40:00+02:00"                      # zadnje čitanje sinoć
    known = {str(100 + i) for i in range(24)} | {str(201 + i) for i in range(23)} | {str(300 + i) for i in range(24)}
    found = {x.source_id for x in src.fetch(INCREMENTAL, known)}
    assert "200" in found                                        # nov oglas na 2. stranici
    # 2. stranica ima nov oglas → čita se 3.; ona je poznata i starija od prošlog čitanja → kraj.
    assert sum("houses-for-sale" in u for u in http.calls) == 3


def test_oglasnik_reads_on_while_page_is_recent():
    from scraper.sources.oglasnik import Oglasnik

    src = Oglasnik(None, Locator(), load_config()["kriteriji"])
    page = oglasnik.parse_page(read("oglasnik_kuce.html.gz"), HOUSE)   # zadnji na stranici: 04.10.2026 u noći
    src.since = "2026-10-03T22:40:00+02:00"
    assert src._recent(page)
    src.since = "2026-10-04T12:00:00+02:00"
    assert not src._recent(page)


def test_fina_notary_sale_and_cadastral_sveta_jelena(fina):
    """Javni bilježnik / stečajni upravitelj: mjesto samo iz opisa (⚠). k.o. Sveta Jelena je
    Crikvenica, ne istoimeno naselje u Mošćeničkoj Dragi."""
    from scraper.filters import evaluate

    x = fina.to_listing(row("(javni bilježnik)", "Građevinsko zemljište k.č. 1234/5 k.o. Njivice, površine 800 m2"))
    assert x and x.municipality == "Omišalj" and any("javni bilježnik" in w for w in x.extra["warnings"])
    assert fina.to_listing(row("(javni bilježnik)", "Građevinsko zemljište k.č. 1 k.o. Sesvete, 800 m2")) is None
    for ko in ("Sveta Jelena", "Sv. Jelena"):
        y = fina.to_listing(row("Općinski sud u Crikvenici", f"Građevinsko zemljište, k.č. 3842/1 k.o. {ko}, površine 800 m2"))
        assert y.municipality == "Crikvenica" and evaluate(y, load_config()["kriteriji"], Locator()).status != "odbijen"


def test_njuskalo_captcha_on_listing_page_defers(monkeypatch, fina):
    """Captcha na stranici oglasa: oglas se ne označava kao otvoren, nego čeka; ostali se
    u tom pokretanju ne otvaraju."""
    from scraper.sources import njuskalo
    from scraper.sources.base import INCREMENTAL

    captcha = "<html><title>Captcha - ShieldSquare</title></html>"
    browser = FakeBrowser({"prodaja-kuca": read("njuskalo_kuce.html.gz"),
                           "prodaja-zemljista": read("njuskalo_zemljista.html.gz"), "oglas-": captcha})
    nj = njuskalo.Njuskalo(None, Locator(), load_config()["kriteriji"], browser=browser)
    nj.since = "2026-10-05T11:30:00+02:00"
    items = {x.source_id: x for x in nj.fetch(INCREMENTAL, {"45180000"})}
    opened = [u for u in browser.calls if "oglas-" in u]
    assert len(opened) == 1 and "51323938" not in items
    assert nj.deferred and not any(x.extra.get("detalji") for x in items.values())


def test_fina_unreadable_csv_is_an_error(fina):
    class Resp:
        def __init__(self, text):
            self.content = text.encode("utf-8")

    class Http:
        def __init__(self, text):
            self.text = text

        def get(self, url, **kw):
            return Resp(self.text)

    for text in ("<html><title>Održavanje</title></html>",
                 "Tijelo;Opis;Vrsta\nOpćinski sud u Rijeci;Građevinsko zemljište k.o. Njivice;nekretnina\n"):
        fina.http = Http(text)
        with pytest.raises(RuntimeError):
            fina.fetch("incremental", set())
    fina.http = None


def test_njuskalo_real_pages_price_on_request_and_per_m2():
    """Stvarni oglasi s Njuškala (spremio Redmi 7. 10., bez osobnih podataka): "cijena na upit"
    luksuzna kuća (riječi u opisu) i kuća s cijenom 3.400 € koja je zapravo cijena po m²."""
    from scraper.filters import evaluate
    from scraper.models import Listing
    from scraper.prices import AskingPrices
    from scraper.sources.njuskalo import parse_detail

    loc, crit = Locator(), load_config()["kriteriji"]
    prices = AskingPrices(loc, {"kuca|Rijeka|": {"n": 50, "med": 2700}})
    upit = Listing("njuskalo", "40387035", "u", "Rijeka, Martinkovac, samostojeća kuća sa prekrasnim pogledom", HOUSE,
                   subtype="Samostojeća kuća", county="Primorsko-goranska")
    parse_detail(read("njuskalo_oglas_na_upit.html.gz"), upit)
    assert (upit.area, upit.plot_area, upit.settlement, upit.price) == (400, 1000, "Martinkovac", None)
    d = evaluate(upit, crit, loc, prices)
    assert d.status == "odbijen" and d.reasons[0].startswith("cijena na upit – luksuzna")
    po_m2 = Listing("njuskalo", "49269565", "u", "Kuća sa tri stana", HOUSE, subtype="Samostojeća kuća", price=3400,
                    county="Primorsko-goranska")
    parse_detail(read("njuskalo_oglas_cijena_po_m2.html.gz"), po_m2)
    assert (po_m2.area, po_m2.plot_area, po_m2.settlement) == (334, 490, "Krasica")
    d = evaluate(po_m2, crit, loc)
    assert "cijena 1.135.600 € > 400.000 €" in d.reasons


def test_empty_category_is_source_error():
    """Jedna kategorija (zemljišta) prazna, a kuće rade: greška izvora, a ne tiho ništa
    (promijenjena adresa kategorije, stranica održavanja s HTTP 200)."""
    from scraper.sources import burza, realestatecroatia, vender
    from scraper.sources.base import INCREMENTAL

    class Resp:
        def __init__(self, text="", data=None):
            self.text, self.data, self.headers = text, data, {}

        def json(self):
            return self.data

    class Http:
        def __init__(self, answer):
            self.answer = answer

        def get(self, url, **kw):
            return self.answer(url)

    cfg, loc = load_config()["kriteriji"], Locator()
    houses = {"code": 1, "title": "Kuća", "price": 900_000, "summary": {"area": 120}, "countyName": "Primorsko-goranska",
              "cityName": "Omišalj", "settlementName": "Njivice", "smartLink": "k"}
    cases = [
        index_oglasi.IndexOglasi(Http(lambda u: Resp(data={"data": [houses] if "houses" in u else [], "nextPage": -1})),
                                 loc, cfg),
        oglasnik.Oglasnik(Http(lambda u: Resp(read("oglasnik_kuce.html.gz") if "kuce" in u else "<html>Održavanje</html>")),
                          loc, cfg),
        realestatecroatia.RealEstateCroatia(
            Http(lambda u: Resp(read("realestatecroatia_kuce.html.gz") if "vrsta=1" in u else "")), loc, cfg),
        burza.Burza(Http(lambda u: Resp(read("burza_kuce.html.gz") if "kuce" in u else "")), loc, cfg),
    ]
    for src in cases:
        with pytest.raises(RuntimeError, match="praz|nema oglasa"):
            src.fetch(INCREMENTAL, set())

    # vender.hr promijeni oznake vrsta: sve bi bilo "nije kuća ni zemljište" i tiho odbijeno.
    data = json.loads(read("vender_pgz.json.gz"))
    for x in data:
        x["property_type"] = [999999]
    with pytest.raises(RuntimeError, match="nijedan oglas"):
        vender.Vender(Http(lambda u: Resp(data=data)), loc, cfg).fetch(INCREMENTAL, set())


def test_hanging_detail_pages_stop_after_time_budget(monkeypatch):
    """Stranice oglasa ne odgovaraju (svaka troši ~85 s): nakon DETAIL_SECONDS izvor ih više
    ne otvara u ovom pokretanju, nego ih odgađa – inače pokretanje prijeđe ograničenje posla."""
    from scraper.sources import base, realestatecroatia
    from scraper.sources.base import INCREMENTAL

    clock = [1000.0]
    monkeypatch.setattr(base.time, "monotonic", lambda: clock[0])
    page = read("realestatecroatia_kuce.html.gz")

    class Resp:
        def __init__(self, text):
            self.text = text

    class Http:
        def __init__(self):
            self.details, self.retries = 0, set()

        def get(self, url, retries=None, **kw):
            if "detail.asp" in url:
                self.details += 1
                self.retries.add(retries)
                clock[0] += 85
                raise RuntimeError("Timeout")
            return Resp(page if url.endswith("page=1") else "")

    http = Http()
    src = realestatecroatia.RealEstateCroatia(http, Locator(), load_config()["kriteriji"])
    src.fetch(INCREMENTAL, set())
    assert http.details == 3 and http.retries == {base.DETAIL_RETRIES}   # 0, 85, 170 s; nakon 255 s staje
    assert len(src.deferred) > 3                                       # ostali čekaju sljedeće pokretanje


def _nj_item(sid, when):
    from datetime import timezone
    return (f'<li class="EntityList-item EntityList-item--n1 EntityList-item--Regular"><article>'
            f'<h3 class="entity-title"><a href="/nekretnine/kuca-oglas-{sid}" name="{sid}" class="l"><span>Kuća {sid}</span>'
            f'</a></h3><div class="entity-description">Samostojeća kuća<br/>Stambena površina: 120 m2<br/>'
            f'Lokacija: Punat, Punat</div><time datetime="{when.astimezone(timezone.utc):%Y-%m-%dT%H:%M:%S.000Z}">x</time>'
            f'<strong class="price price--eur">500.000 €</strong></article></li>')


def test_njuskalo_page_cap_leaves_gap_for_next_run():
    """Više novih oglasa od 4 stranice (jutro nakon noći): čitanje je nepotpuno (runner ne
    pomiče "since"), a sljedeće pokretanje (catch_up) čita do 10 stranica."""
    from datetime import datetime, timedelta, timezone

    from scraper.sources.base import INCREMENTAL
    from scraper.sources.njuskalo import Njuskalo

    now = datetime(2026, 10, 8, 7, 10, tzinfo=timezone.utc)
    pages = ["<ul>" + "".join(_nj_item(60_000_000 - p * 25 - i, now - timedelta(minutes=p * 25 + i))
                              for i in range(25)) + "</ul>" for p in range(8)]

    class Browser:
        calls = []

        def get(self, url, wait_selector="body"):
            Browser.calls.append(url)
            if "prodaja-kuca" in url:
                n = int(url.split("page=")[1]) if "page=" in url else 1
                return pages[n - 1] if n <= len(pages) else "<ul></ul>"
            if "prodaja-zemljista" in url:
                return pages[-1]                                  # zemljišta: već prva je starija
            return "<html><title>prazno</title></html>"

        def close(self):
            pass

    src = Njuskalo(None, Locator(), load_config()["kriteriji"], browser=Browser())
    src.since = (now - timedelta(minutes=150)).isoformat()      # s 15 min zalihe: 7 stranica
    src.fetch(INCREMENTAL, {"1"})
    assert src.incomplete and sum("prodaja-kuca" in u for u in Browser.calls) == 4
    Browser.calls.clear()
    src.catch_up = True
    src.fetch(INCREMENTAL, {"1"})
    assert not src.incomplete and sum("prodaja-kuca" in u for u in Browser.calls) == 7


def test_nekretnine_reads_modified_while_prices_change(monkeypatch):
    """"Nedavno izmijenjeni" (sniženja): čita se dalje dok stranica ima nov oglas ili promijenjenu
    cijenu (ujutro nakon noći ih je više od jedne stranice), najviše 10."""
    from scraper.sources import nekretnine_hr
    from scraper.sources.base import INCREMENTAL

    def page_of(url):
        return int(url.split("pag=")[1])

    def fake_parse(text, kind):
        n, sort = text
        if sort != "dataModifica" or kind != HOUSE:
            return [], 1
        xs = [Listing(source="nekretnine_hr", source_id=f"{n}{i:02d}", url="u", title="Kuća", kind=HOUSE,
                      price=380_000 if n <= 2 else 500_000) for i in range(25)]
        return xs, 20

    class Http:
        calls = []

        def get(self, url, **kw):
            Http.calls.append(url)
            return SimpleNamespace(text=(page_of(url), "dataModifica" if "dataModifica" in url else "data"))

    from types import SimpleNamespace
    monkeypatch.setattr(nekretnine_hr, "parse_page", fake_parse)
    src = nekretnine_hr.NekretnineHr(Http(), Locator(), load_config()["kriteriji"])
    known = {f"{n}{i:02d}" for n in range(1, 21) for i in range(25)}
    src.known_prices = {k: 500_000 for k in known}                     # str. 1–2: sniženo na 380.000
    src.fetch(INCREMENTAL, known)
    modified = [page_of(u) for u in Http.calls if "dataModifica" in u and "samostojeca" in u]
    assert modified == [1, 2, 3]                                        # 3.: bez promjena → dalje ne


def test_realestatecroatia_daily_deep_read_finds_price_drop(monkeypatch):
    """Popis je po broju oglasa: oglas koji je bio skuplji od granice pa pojeftinio pojavi se
    duboko. Jednom dnevno (deep) čita se cijeli popis do granice cijene."""
    from scraper.sources import realestatecroatia as rc
    from scraper.sources.base import INCREMENTAL

    def fake_parse(text, kind):
        vrsta, page = text
        if kind != HOUSE:                                               # zemljišta: jedno, poznato
            return [Listing(source="realestatecroatia", source_id="5", url="u", title="Zemljište", kind=LAND,
                            price=100_000, area=800, extra={"istaknut": False})]
        if page > 3:
            return []
        start = 3000 - (page - 1) * rc.PAGE_SIZE
        return [Listing(source="realestatecroatia", source_id=str(start - i), url="u", title="Kuća", kind=HOUSE,
                        price=380_000, area=120, extra={"istaknut": False}) for i in range(rc.PAGE_SIZE)]

    monkeypatch.setattr(rc, "parse_list", fake_parse)
    src = rc.RealEstateCroatia(None, Locator(), load_config()["kriteriji"])
    src._list = lambda vrsta, cap, page: (vrsta, page)
    src.worth_detail = lambda x: False
    known = {str(i) for i in range(2900, 3001)} | {"5"}
    known.discard("2945")                                               # pojeftinio, duboko na 3. stranici
    assert "2945" not in {x.source_id for x in src.fetch(INCREMENTAL, known)}   # redovno: staje na 1. str.
    src.deep = True
    assert "2945" in {x.source_id for x in src.fetch(INCREMENTAL, known)}


def test_njuskalo_catchup_captcha_deep_keeps_pages_read():
    """Sustizanje (do 10 stranica) je dodatak: captcha na 5.+ stranici ne ruši izvor – pročitano
    ostaje, dublje se više ne čita (ni u drugoj kategoriji), a nepročitano javlja runner."""
    from datetime import datetime, timedelta, timezone

    from scraper.sources.base import INCREMENTAL
    from scraper.sources.njuskalo import Njuskalo

    now = datetime(2026, 10, 8, 7, 10, tzinfo=timezone.utc)
    pages = ["<ul>" + "".join(_nj_item(60_000_000 - p * 25 - i, now - timedelta(minutes=p * 25 + i))
                              for i in range(25)) + "</ul>" for p in range(10)]

    class Browser:
        calls = []

        def get(self, url, wait_selector="body"):
            Browser.calls.append(url)
            n = int(url.split("page=")[1]) if "page=" in url else 1
            if "prodaja-kuca" in url or "prodaja-zemljista" in url:
                return "<html><head><title>Captcha</title></head></html>" if n >= 5 else pages[n - 1]
            return "<html><title>prazno</title></html>"

        def close(self):
            pass

    src = Njuskalo(None, Locator(), load_config()["kriteriji"], browser=Browser())
    src.since = (now - timedelta(hours=5)).isoformat()
    src.catch_up = True
    found = src.fetch(INCREMENTAL, {"1"})
    assert len({x.source_id for x in found} | {x.source_id for x in src.deferred}) == 100   # 4 stranice kuća
    assert src.incomplete and "captchu" in src.deep_error and src.reached.startswith("2026-10-08T")
    assert sum("prodaja-kuca" in u for u in Browser.calls) == 5          # 5. je captcha, dalje ništa
    assert sum("prodaja-zemljista" in u for u in Browser.calls) == 4     # druga kategorija: ne dublje


def test_realestatecroatia_deep_page_error_keeps_regular_read(monkeypatch):
    """Greška na dubokoj stranici dnevnog dubljeg čitanja ne ruši izvor: novi oglasi s vrha
    ostaju, greška se bilježi (deep_error). Greška na stranici redovnog čitanja i dalje ruši."""
    import pytest

    from scraper.sources import realestatecroatia as rc
    from scraper.sources.base import INCREMENTAL

    def fake_parse(text, kind):
        vrsta, page = text
        if kind != HOUSE:
            return [Listing(source="realestatecroatia", source_id="5", url="u", title="Zemljište", kind=LAND,
                            price=100_000, area=800, extra={"istaknut": False})]
        start = 3001 - (page - 1) * rc.PAGE_SIZE
        return [Listing(source="realestatecroatia", source_id=str(start - i), url="u", title="Kuća", kind=HOUSE,
                        price=380_000, area=120, extra={"istaknut": False}) for i in range(rc.PAGE_SIZE)]

    def fake_list(vrsta, cap, page):
        if page == bad["page"]:
            raise RuntimeError("HTTP 500")
        return (vrsta, page)

    bad = {"page": 4}
    monkeypatch.setattr(rc, "parse_list", fake_parse)
    src = rc.RealEstateCroatia(None, Locator(), load_config()["kriteriji"])
    src._list = fake_list
    src.worth_detail = lambda x: False
    known = {str(i) for i in range(2800, 3001)} | {"5"}                  # nov je samo 3001
    src.deep = True
    ids = {x.source_id for x in src.fetch(INCREMENTAL, known)}
    assert "3001" in ids and "HTTP 500" in src.deep_error and "stranica 4" in src.deep_error
    bad["page"] = 1                                                       # redovno čitanje: greška izvora
    with pytest.raises(RuntimeError):
        src.fetch(INCREMENTAL, known)


def test_detail_parsers_reject_empty_pages():
    """Stranica oglasa bez ičega prepoznatljivog (promjena stranice) je greška, ne "oglas bez
    podataka" – inače nadzor stranica oglasa ne bi ništa vidio."""
    import pytest

    from scraper.sources import burza, index_oglasi, realestatecroatia

    x = Listing(source="t", source_id="1", url="u", title="Kuća", kind=HOUSE)
    for call in (lambda: realestatecroatia.parse_detail("<html>nova stranica</html>", x),
                 lambda: burza.parse_detail("<html>nova stranica</html>", x),
                 lambda: index_oglasi.parse_single({"data": []}, x)):
        with pytest.raises(ValueError):
            call()


def test_njuskalo_empty_list_page_is_saved_and_described(tmp_path, monkeypatch):
    """Popis bez oglasa (zaštita koja ne piše "captcha" ili promjena stranice): poruka o grešci
    nosi naslov stranice, a stranica se sprema za slanje (redmi_probe.py --posalji)."""
    import gzip

    import pytest

    from scraper.sources import njuskalo
    from scraper.sources.base import INCREMENTAL

    monkeypatch.setattr(njuskalo, "FAILED_PAGES", tmp_path)
    page = "<html><head><title>Pardon Our Interruption</title></head><body>x</body></html>"
    src = njuskalo.Njuskalo(None, Locator(), load_config()["kriteriji"], browser=FakeBrowser({"prodaja-kuca": page}))
    with pytest.raises(RuntimeError, match="Pardon Our Interruption"):
        src.fetch(INCREMENTAL, set())
    saved = list(tmp_path.glob("*_njuskalo_greska_prodaja-kuca.html.gz"))
    assert len(saved) == 1 and b"Pardon" in gzip.decompress(saved[0].read_bytes())


def test_njuskalo_new_list_layout_october_2026(fina):
    """Novi izgled popisa (8. 10. 2026.): <li class="listing">, mjesto "Naselje - Općina", podaci u
    "highlights". Blok agencije na vrhu i "Posljednji oglasi" cijelog Njuškala nisu oglasi popisa."""
    from scraper.sources.base import INCREMENTAL
    from scraper.sources.njuskalo import Njuskalo, parse_list

    page = read("njuskalo_kuce_2026-10.html.gz")
    items = {x.source_id: x for x in parse_list(page, HOUSE)}
    assert len(items) == 33 and sum(x.extra["istaknut"] for x in items.values()) == 9
    assert "51175192" not in items and "51777157" not in items        # blok agencije, "Posljednji oglasi"
    # "Super Vau" sa strane (bez broja, cijene, mjesta): 47749175 je i na popisu (s podacima).
    assert not items["47749175"].extra.get("bez_podataka") and items["47749175"].price
    assert items["43488416"].extra["bez_podataka"] and items["43488416"].price is None
    x = items["50863567"]
    assert (x.price, x.area, x.plot_area, x.subtype) == (450_000, 138, 316, "Samostojeća kuća")
    assert (x.municipality, x.settlement) == ("Krk", "Vrh") and not x.extra["istaknut"]
    assert x.published == "2026-10-08T14:32:40.000Z" and x.url.endswith("-oglas-50863567")
    assert (items["49408567"].municipality, items["49408567"].settlement) == ("Novi Vinodolski", "Novi Vinodolski")
    opatija = next(x for x in items.values() if x.municipality == "Opatija")
    assert opatija.settlement == "Opatija - Centar"
    # Cijeli dohvat s novim izgledom ne javlja "nema oglasa".
    browser = FakeBrowser({"prodaja-kuca": page, "prodaja-zemljista": read("njuskalo_zemljista.html.gz")})
    src = Njuskalo(None, Locator(), load_config()["kriteriji"], browser=browser)
    src.since = "2026-10-08T16:20:00+02:00"
    found = src.fetch(INCREMENTAL, {"1", "43488416"})
    ids = {x.source_id for x in found} | {x.source_id for x in src.deferred}
    assert "50863567" in ids
    assert "43488416" not in ids                       # poznat "Super Vau" bez podataka: ništa se ne prepisuje
    assert "47749180" in ids                           # nov "Super Vau": otvara se (ili čeka otvaranje)
    assert any("47749180" in u for u in browser.calls) or "47749180" in {x.source_id for x in src.deferred}


def test_njuskalo_list_without_dates_is_an_error():
    """Popis bez datuma objave (promjena stranice): ne zna se dokle čitati – greška izvora, a ne
    tiho čitanje samo prve stranice."""
    import pytest

    from scraper.sources.base import INCREMENTAL
    from scraper.sources.njuskalo import Njuskalo

    page = read("njuskalo_kuce_2026-10.html.gz")
    no_dates = re.sub(r'<time datetime="[^"]*"', "<time", page)
    src = Njuskalo(None, Locator(), load_config()["kriteriji"], browser=FakeBrowser({"prodaja-kuca": no_dates}))
    src.since = "2026-10-08T16:20:00+02:00"
    with pytest.raises(RuntimeError, match="nemaju datum"):
        src.fetch(INCREMENTAL, {"1"})


def test_realestatecroatia_deep_read_resumes_where_it_stopped(monkeypatch):
    """Dublje čitanje ograničeno vremenom: sljedeće pokretanje nastavlja od stranice gdje je stalo
    (jednu ranije – novi oglasi guraju popis), dok popis nije pročitan do kraja."""
    from scraper.sources import realestatecroatia as rc
    from scraper.sources.base import INCREMENTAL

    def fake_parse(text, kind):
        vrsta, page = text
        if kind != HOUSE:
            return [Listing(source="realestatecroatia", source_id="5", url="u", title="Zemljište", kind=LAND,
                            price=100_000, area=800, extra={"istaknut": False})]
        if page > 9:
            return []
        start = 3001 - (page - 1) * rc.PAGE_SIZE
        return [Listing(source="realestatecroatia", source_id=str(start - i), url="u", title="Kuća", kind=HOUSE,
                        price=380_000, area=120, extra={"istaknut": False}) for i in range(rc.PAGE_SIZE)]

    clock = {"t": 0.0}
    pages = []

    def fake_list(vrsta, cap, page):
        clock["t"] += 100                                                  # svaka stranica "100 s"
        pages.append(page)
        return (vrsta, page)

    monkeypatch.setattr(rc, "parse_list", fake_parse)
    monkeypatch.setattr(rc.time, "monotonic", lambda: clock["t"])
    src = rc.RealEstateCroatia(None, Locator(), load_config()["kriteriji"])
    src._list = fake_list
    src.worth_detail = lambda x: False
    known = {str(i) for i in range(2700, 3001)} | {"5"}
    src.deep, src.deep_from = True, {}
    src.fetch(INCREMENTAL, known)
    assert src.deep_reached == {"kuca": 4}                                 # 240 s: stranice 1–3
    pages.clear()
    src.deep_from = src.deep_reached
    src.fetch(INCREMENTAL, known)
    assert pages == [1, 3, 4, 1] and src.deep_reached == {"kuca": 5}     # 1. (novi), pa od 3.; zemljišta
    for _ in range(10):
        if not src.deep_reached:
            break
        src.deep_from = src.deep_reached
        pages.clear()
        src.fetch(INCREMENTAL, known)
    assert 10 in pages and src.deep_reached == {}                          # do kraja popisa


def test_njuskalo_detail_reads_approximate_circle_radius():
    """Približna lokacija na Njuškalu je krug na karti; polumjer je u podacima stranice (mapBox)."""
    from scraper.sources.njuskalo import parse_detail

    x = Listing(source="njuskalo", source_id="1", url="u", title="Kuća", kind=HOUSE)
    page = ('<div class="ClassifiedDetail"></div><script>{"coordinates":{"latitude":45.16,"longitude":14.60},'
            '"isApproximateLocationOnMap":true},"mapBox":{"showPointsOfInterestControls":true,'
            '"showNearbyListingsControl":true,"circle":{"radius":500,"paint":{"circle-opacity":0.2}}}</script>')
    parse_detail(page, x)
    assert x.extra["priblizna_lokacija"] and x.extra["krug_m"] == 500
    y = Listing(source="njuskalo", source_id="2", url="u", title="Kuća", kind=HOUSE)
    parse_detail(page.replace('"isApproximateLocationOnMap":true', '"isApproximateLocationOnMap":false'), y)
    assert "krug_m" not in y.extra


def test_strip_contacts_keeps_coordinates_prices_and_dates():
    from scraper.text import strip_contacts
    assert strip_contacts("Tel: 091/503-2253, +385 51 341 080. E-mail: ana.b@agencija.com") == \
        "Tel: [telefon], [telefon]. E-mail: [e-adresa]"
    kept = '"latitude":45.2969275,"longitude":14.2723701 · 1.250.000 € · 2026-10-09T07:01:06 · k.č. 1234/5 · ID 16439'
    assert strip_contacts(kept) == kept


def test_strip_contacts_croatian_formats():
    from scraper.text import strip_contacts
    for phone in ("091.503.2253", "(051) 341-080", "+385 (0)91 5032253", "0915032253", "051 341 080"):
        assert strip_contacts(f"Tel {phone}.") == "Tel [telefon].", phone
    assert strip_contacts("ivan(at)gmail.com, ivan.horvat [at] gmail.com") == "[e-adresa], [e-adresa]"
    assert strip_contacts("k.č. 2345/12 2345/13 k.o. Vrh, 0.523, 09.10.2026.") == "k.č. 2345/12 2345/13 k.o. Vrh, 0.523, 09.10.2026."


def test_field_census_records_njuskalo_fields(tmp_path):
    """Revizija 23. 10.: Redmi bilježi nazive polja sa stranica Njuškala (GitHub do njih ne dolazi)
    u meta "popis_polja:njuskalo:VRSTA", najviše MAX_PAGES stranica po vrsti."""
    import json

    from scraper import popis_polja
    from scraper.db import State
    from scraper.models import Listing
    from scraper.sources import njuskalo

    popis_polja._seen.clear()
    state = State(tmp_path / "s.db")
    for _ in range(2):
        njuskalo.parse_detail(read("njuskalo_kuca_oglas.html.gz"), Listing("njuskalo", "1", "u", "Kuća", HOUSE, price=1))
    popis_polja.save(state)
    data = json.loads(state.meta_get("popis_polja:njuskalo:kuca"))
    assert data["stranica"] == 2 and data["polja"]["tip kuće"] == {"n": 2, "primjeri": ["Samostojeća"]}
    assert data["polja"]["svojstvo: Gradski vodovod"]["n"] == 2 and not popis_polja._seen
    state.meta_set("popis_polja:njuskalo:kuca", json.dumps({"stranica": popis_polja.MAX_PAGES, "polja": {}}))
    njuskalo.parse_detail(read("njuskalo_kuca_oglas.html.gz"), Listing("njuskalo", "1", "u", "Kuća", HOUSE, price=1))
    popis_polja.save(state)
    assert json.loads(state.meta_get("popis_polja:njuskalo:kuca")) == {"stranica": popis_polja.MAX_PAGES, "polja": {}}
    state.close()
