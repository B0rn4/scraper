from scraper.ispu import PointInfo, check_land, parcels_in_text, to_htrs, wkt_centroid


class FakeIspu:
    def __init__(self, info, parcels=None):
        self.info, self.parcels, self.calls = info, parcels or {}, []

    def parcel(self, ko, kc, names=None):
        self.calls.append(("parcel", ko, kc))
        return self.parcels.get((ko, kc))

    def identify(self, x, y):
        self.calls.append(("identify", round(x), round(y)))
        return self.info

    def point(self, lat, lon):
        return self.identify(*to_htrs(lat, lon))


def test_projection_and_centroid():
    x, y = to_htrs(45.0272, 14.5753)          # središte Krka; pyproj: 348330.468, 4989270.901
    assert abs(x - 348330.468) < 0.01 and abs(y - 4989270.901) < 0.01
    assert wkt_centroid("POLYGON ((0 0, 10 0, 10 10, 0 10, 0 0))") == (5.0, 5.0)


def test_parcels_in_text():
    assert parcels_in_text("Zemljište k.č. 1234/5, k.o. Njivice.") == [("Njivice", "1234/5")]
    assert parcels_in_text("z.k.ul. 567 k.o. Vrh, kčbr. 3058/2 i 3058/3") == [("Vrh", "3058/2"), ("Vrh", "3058/3")]
    assert parcels_in_text("čestica br. 1020 K.O. Sveti Vid-Miholjice") == [("Sveti Vid-Miholjice", "1020")]
    assert parcels_in_text("Pogled na more, 600 m2.") == []


def test_check_land_by_parcel_and_by_map():
    inside = PointInfo(gp="naselja", use="(GP) IZGRAĐENI DIO GRAĐEVINSKOG PODRUČJA NASELJA", block="NJIVICE - GRAĐEVINSKO",
                       land_values=[158.0, 219.0])
    fake = FakeIspu(inside, {("Njivice", "12/3"): {"x": 340000.0, "y": 5000000.0, "povrsina": 1250}})
    r = check_land(fake, "Zemljište k.č. 12/3 k.o. Njivice", None, None, True)
    assert r.line == "🗺 U građevinskom području naselja (izgrađeni dio) – ISPU, prema k.č. 12/3 k.o. Njivice, 1.250 m²"
    assert not r.warning and r.info.land_values == [158.0, 219.0]

    outside = PointInfo(gp=None, use="(Š1) GOSPODARSKA ŠUMA")
    r = check_land(FakeIspu(outside), "Zemljište s pogledom", 45.09, 14.59, False)
    assert r.line.startswith("🗺 NIJE u građevinskom području – ISPU, prema oznaci na karti oglasa")
    assert r.warning == "prema ISPU-u nije u građevinskom području (Gospodarska šuma) – provjeri (oznaka može biti približna)"

    r = check_land(FakeIspu(PointInfo(gp="izvan naselja", use="(T1) UGOSTITELJSKO - TURISTIČKA NAMJENA")),
                   "", 45.1, 14.5, False)
    assert "IZVAN naselja" in r.line and "nije za obiteljsku kuću" in r.warning

    fake = FakeIspu(inside)
    r = check_land(fake, "Zemljište", 45.1, 14.5, True)        # približna lokacija → ne provjerava se
    assert r.line.endswith("oglas nema točnu lokaciju ni broj čestice") and not fake.calls


def test_runner_marks_land_outside_building_zone(tmp_path):
    from scraper.models import LAND, PASS, WARN, Decision, Listing
    from scraper.notify import format_listing
    from scraper.runner import Runner

    runner = Runner(tmp_path / "s.db", tmp_path, send=False)
    runner._ispu = FakeIspu(PointInfo(gp=None, use="(Š1) GOSPODARSKA ŠUMA", block="LAKMARTIN - ŠUMA"))
    x = Listing(source="nekretnine_hr", source_id="1", url="u", title="Zemljište Brzac", kind=LAND,
                price=60_000, area=600, extra={"lat": 45.09, "lon": 14.59, "priblizna_lokacija": False})
    d = Decision(PASS, jls="Krk")
    runner._check_land(x, d)
    assert d.status == WARN and d.warnings[0].startswith("prema ISPU-u nije u građevinskom području")
    text = format_listing(x, d)
    assert "🗺 NIJE u građevinskom području" in text and "⚠ prema ISPU-u" in text

    runner._ispu = FakeIspu(PointInfo(gp="naselja", use="(GP) NEIZGRAĐENI DIO", block="BRZAC - GRAĐEVINSKO",
                                      land_values=[130.0]))
    y = Listing(source="nekretnine_hr", source_id="2", url="u", title="Zemljište Brzac", kind=LAND,
                price=120_000, area=600, extra={"lat": 45.09, "lon": 14.59, "priblizna_lokacija": False})
    d = Decision(PASS, jls="Krk")
    runner._check_land(y, d)
    assert d.status == PASS and "(neizgrađeni dio)" in y.extra["gp"]
    assert y.extra["ppv"] == "🏛 PPV 2026. (na lokaciji, blok Brzac - Građevinsko): građevinsko 130 €/m² – oglas 55 % iznad gornje"


def test_runner_house_building_zone(tmp_path):
    """Kuća: izvan građevinskog područja → samo ⚠; bez točne lokacije redak se prvi izostavlja."""
    from scraper.models import HOUSE, PASS, WARN, Decision, Listing
    from scraper.notify import format_listing
    from scraper.runner import Runner

    runner = Runner(tmp_path / "s.db", tmp_path, send=False)
    runner._ispu = FakeIspu(PointInfo(gp=None, use="(P2) VRIJEDNO OBRADIVO TLO", land_values=[20.0]))
    x = Listing(source="index_oglasi", source_id="1", url="u", title="Kuća Rasopasno", kind=HOUSE,
                price=250_000, area=120, extra={"lat": 45.1, "lon": 14.6, "priblizna_lokacija": False})
    d = Decision(PASS, jls="Dobrinj")
    runner._check_land(x, d)
    assert d.status == WARN and d.warnings[0].startswith("prema ISPU-u kuća nije u građevinskom području (Vrijedno")
    assert "ppv" not in x.extra and not x.extra["gp_neprovjereno"]     # PPV zemljišta nije za kuće

    fake = FakeIspu(PointInfo(gp="naselja", use="(GP) IZGRAĐENI DIO"))
    runner._ispu = fake
    y = Listing(source="index_oglasi", source_id="2", url="u", title="Kuća Njivice", kind=HOUSE,
                price=250_000, area=120, extra={"lat": 45.1, "lon": 14.6, "priblizna_lokacija": True})
    d = Decision(PASS, jls="Omišalj")
    runner._check_land(y, d)
    assert d.status == PASS and y.extra["gp_neprovjereno"] and not fake.calls
    assert "nije provjereno" in format_listing(y, d)
    y.description = "x" * 50
    y.extra["usporedba"] = "📈 " + "dugačka usporedba " * 30
    y.extra["ppv"] = "🏛 " + "dugačak PPV " * 30
    assert "nije provjereno" not in format_listing(y, d)                # prvi otpada kad je poruka preduga


def _heritage_layer(catalog, label, name, number, kind, classification):
    fields = {"Naziv": name, "Županija": "Primorsko-goranska županija", "Vrsta": kind, "Klasifikacija": classification,
              "Registarski broj": number, "Status zaštite": "Zaštićeno kulturno dobro", "Zona": "G"}
    return {"catalogId": catalog, "label": {"hr": label},
            "items": [{"title": label, "items": [{"label": {"hr": k}, "value": v} for k, v in fields.items()]}]}


def test_heritage_from_identify_and_check():
    from scraper.ispu import parse_identify

    krk = "Kulturno-povijesna urbanistička cjelina grada Krka"
    data = [{"catalogId": "1", "label": {"hr": "Građevinsko područje naselja"}, "items": [{"items": []}]},
            _heritage_layer("326", "Zaštićena kulturna dobra", krk, "Z-2684", "Kulturnopovijesne cjeline", "urbana cjelina"),
            _heritage_layer("341", "Urbane cjeline", krk, "Z-2684", "Kulturnopovijesne cjeline", "urbana cjelina"),
            _heritage_layer("326", "Zaštićena kulturna dobra", "Kuća Fanfogna", "Z-1234", "Pojedinačna kulturna dobra",
                            "stambena građevina")]
    info = parse_identify(data)
    assert info.gp == "naselja" and [h.number for h in info.heritage] == ["Z-2684", "Z-1234"]
    assert info.heritage[0].area and not info.heritage[1].area

    r = check_land(FakeIspu(info), "Kuća u Krku", 45.0266, 14.5755, False, house=True)
    assert not r.warning and r.heritage.startswith(f"u kulturno-povijesnoj cjelini „{krk}” (Z-2684); zaštićeno kulturno dobro „Kuća Fanfogna”")
    assert r.heritage.endswith("radovi uz uvjete konzervatora (oznaka može biti približna)")

    # Približna oznaka: samo kad opis spominje staru jezgru, i samo cjeline.
    fake = FakeIspu(info)
    r = check_land(fake, "Kamena kuća u staroj gradskoj jezgri Krka", 45.0266, 14.5755, True, house=True)
    assert r.line.startswith("🗺 Građevinsko područje: nije provjereno")
    assert r.heritage.startswith("vjerojatno u kulturno-povijesnoj cjelini") and "Fanfogna" not in r.heritage
    fake = FakeIspu(info)
    assert not check_land(fake, "Kuća s pogledom na more", 45.0266, 14.5755, True, house=True).heritage and not fake.calls


def test_runner_heritage_warning(tmp_path):
    from scraper.ispu import Heritage
    from scraper.models import HOUSE, PASS, WARN, Decision, Listing
    from scraper.runner import Runner

    runner = Runner(tmp_path / "s.db", tmp_path, send=False)
    runner._ispu = FakeIspu(PointInfo(gp="naselja", use="(GP) IZGRAĐENI DIO",
                                      heritage=[Heritage("Kulturno-povijesna cjelina grada Opatije", "Z-5520",
                                                         "Kulturnopovijesne cjeline", "urbana cjelina")]))
    x = Listing(source="vender", source_id="1", url="u", title="Kuća Opatija", kind=HOUSE, price=390_000, area=120,
                extra={"lat": 45.3376, "lon": 14.3058, "priblizna_lokacija": False})
    d = Decision(PASS, jls="Opatija")
    runner._check_land(x, d)
    assert d.status == WARN and d.warnings == [
        "u kulturno-povijesnoj cjelini „Kulturno-povijesna cjelina grada Opatije” (Z-5520) – radovi uz uvjete "
        "konzervatora (oznaka može biti približna)"]
