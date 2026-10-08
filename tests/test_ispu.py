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
    r = check_land(fake, "Zemljište", 45.1, 14.5, True)        # približna lokacija bez provjere okolice
    assert r.line.endswith("oglas nema točnu lokaciju ni broj čestice") and not fake.calls


class ShareIspu(FakeIspu):
    def __init__(self, shares):
        super().__init__(None)
        self.shares = shares

    def gp_share(self, lat, lon, radius):
        self.calls.append(("gp_share", lat, lon, radius))
        return PointInfo(gp="naselja", block="RUKAVAC - GRAĐEVINSKO PODRUČJE"), self.shares


def test_check_land_around_approximate_marker():
    """Približna oznaka (krug na portalu): točan udio kruga u građevinskom području, samo postoci (bez ⚠)."""
    r = check_land(ShareIspu({"naselja": 0.998}), "Zemljište", 45.33, 14.29, True, radius=250)
    assert r.line == ("🗺 Krug 250 m oko približne oznake na karti (Rukavac): 100 % u građevinskom području naselja "
                      "– ISPU; točnu česticu provjeri") and not r.warning
    r = check_land(ShareIspu({}), "Zemljište", 45.33, 14.29, True, radius=250)
    assert "0 % u građevinskom području naselja, ostatak izvan –" in r.line and not r.warning
    r = check_land(ShareIspu({"naselja": 0.523, "izvan naselja": 0.05}), "Zemljište", 45.33, 14.29, True, radius=250)
    assert r.line == ("🗺 Krug 250 m oko približne oznake na karti (Rukavac): 52 % u građevinskom području naselja, "
                      "5 % izvan naselja, ostatak izvan građevinskog područja – ISPU; točnu česticu provjeri")
    assert not r.warning
    fake = ShareIspu({"naselja": 1.0})
    r = check_land(fake, "Kuća", 45.33, 14.29, True, house=True)       # kuće: bez provjere okolice
    assert "nije provjereno" in r.line and not fake.calls


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
    assert y.extra["ppv"] == "🏛 PPV (na lokaciji, blok Brzac - Građevinsko): građevinsko 130 €/m² – oglas 55 % iznad gornje"


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

    # Zemljište: nova gradnja nije zabranjena, ali uz uvjete konzervatora.
    r = check_land(FakeIspu(info), "Građevinsko zemljište Krk", 45.0266, 14.5755, False)
    assert r.heritage.endswith("nova gradnja uz uvjete konzervatora (oblik, visina, materijali) (oznaka može biti približna)")
    arch = parse_identify([_heritage_layer("326", "Zaštićena kulturna dobra", "Arheološka zona Fulfinum", "Z-555",
                                           "Arheološka baština", "arheološka zona")])
    assert check_land(FakeIspu(arch), "Zemljište Omišalj", 45.2, 14.55, False).heritage.endswith(
        "gradnja uz uvjete konzervatora (moguća arheološka istraživanja) (oznaka može biti približna)")


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


def test_identify_retries_then_drops_heritage_layers():
    from scraper.ispu import Ispu

    class Resp:
        def __init__(self, status, data=None):
            self.status_code, self.data = status, data

        def json(self):
            return self.data

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(self.status_code)

    class Session:
        def __init__(self, statuses):
            self.statuses, self.bodies = list(statuses), []

        def post(self, url, json=None, **kw):
            self.bodies.append(json)
            return Resp(self.statuses.pop(0), [])

    gp = {"id": "1", "hashIdentify": "a", "_path": "Građevinska područja > Građevinsko područje naselja"}
    z = {"id": "326", "hashIdentify": "b", "_path": "Ministarstvo kulture > Zaštićena kulturna dobra (Z-lista) > Zaštićena kulturna dobra"}

    def ispu(statuses):
        s = Session(statuses)
        i = Ispu(session=s)
        i._layers, i.retry_pause = [gp, z], 0
        return i, s

    i, s = ispu([400, 200])                       # prolazna greška: drugi pokušaj sa svim slojevima
    assert i.identify(1.0, 2.0).heritage_checked and len(s.bodies) == 2 and len(s.bodies[1]["layers"]) == 2
    i, s = ispu([400, 400, 200])                  # i drugi put: bez kulturnih dobara
    info = i.identify(1.0, 2.0)
    assert not info.heritage_checked and [la["id"] for la in s.bodies[2]["layers"]] == ["1"]
    r = check_land(FakeIspu(PointInfo(gp="naselja", heritage_checked=False)), "Kuća", 45.1, 14.5, False, house=True)
    assert r.line.endswith("(kulturna dobra nisu provjerena – ISPU nije odgovorio)")


def test_gp_share_exact_area_from_building_zone_outlines():
    """Obrisi građevinskih područja (KML s GeoServera): točan udio kruga u svakom sloju, s rupama."""
    import math

    from scraper.ispu import Ispu, clip_area, to_htrs

    lat, lon = 45.36394, 14.29046
    cx, cy = to_htrs(lat, lon)

    def to_wgs(x, y):          # obrnuto od to_htrs, Newtonom (dovoljno za test)
        la, lo = lat, lon
        for _ in range(5):
            px, py = to_htrs(la, lo)
            la += (y - py) / 111_200
            lo += (x - px) / (111_200 * math.cos(math.radians(la)))
        return la, lo

    def kml(rings):
        def coords(pts):
            return " ".join(f"{lo},{la},0" for la, lo in (to_wgs(x, y) for x, y in pts))
        polys = "".join(f"<Polygon><outerBoundaryIs><LinearRing><coordinates>{coords(outer)}</coordinates></LinearRing>"
                        f"</outerBoundaryIs>" + "".join(f"<innerBoundaryIs><LinearRing><coordinates>{coords(h)}"
                                                        f"</coordinates></LinearRing></innerBoundaryIs>" for h in holes)
                        + "</Polygon>" for outer, holes in rings)
        return f'<?xml version="1.0"?><kml><Document><Placemark id="gp.1"><MultiGeometry>{polys}</MultiGeometry></Placemark></Document></kml>'

    east_half = [(cx, cy - 1000), (cx + 1000, cy - 1000), (cx + 1000, cy + 1000), (cx, cy + 1000)]
    hole = [(cx + 10, cy - 10), (cx + 30, cy - 10), (cx + 30, cy + 10), (cx + 10, cy + 10)]
    west_strip = [(cx - 1000, cy - 1000), (cx - 50, cy - 1000), (cx - 50, cy + 1000), (cx - 1000, cy + 1000)]

    class Resp:
        def __init__(self, text=None, data=None):
            self.status_code, self.text, self.data, self.headers = 200, text or "", data, {}

        def json(self):
            return self.data

        def raise_for_status(self):
            pass

    class Session:
        def __init__(self):
            self.wms = []

        def post(self, url, json=None, **kw):
            return Resp(data=[])

        def get(self, url, params=None, **kw):
            self.wms.append(params["LAYERS"])
            return Resp(kml([(east_half, [hole])]) if params["LAYERS"] == "225" else kml([(west_strip, [])]))

    gp = {"id": "132", "hashIdentify": "a", "serviceId": "10", "layers": "225", "hash": "h1",
          "label": {"hr": "Građevinsko područje naselja"}, "_path": "Građevinska područja (rujan 2024.) > Građevinsko područje naselja"}
    out = {"id": "134", "hashIdentify": "b", "serviceId": "10", "layers": "224", "hash": "h2",
           "label": {"hr": "Građevinsko područje izvan naselja"}, "_path": "Građevinska područja (rujan 2024.) > Građevinsko područje izvan naselja"}
    s = Session()
    i = Ispu(session=s)
    i._layers, i.retry_pause = [gp, out], 0
    _, shares = i.gp_share(lat, lon, 100)
    full = math.pi * 100 ** 2
    assert abs(shares["naselja"] - (full / 2 - 400) / full) < 0.003                  # pola kruga bez rupe 20×20 m
    segment = 100 ** 2 * math.acos(0.5) - 50 * math.sqrt(100 ** 2 - 50 ** 2)          # odsječak iza x = -50 m
    assert abs(shares["izvan naselja"] - segment / full) < 0.003
    assert sorted(s.wms) == ["224", "225"]
    assert clip_area([], (0, 0, 1, 1), [(0, 0), (1, 0), (0, 1)]) == 0.0
