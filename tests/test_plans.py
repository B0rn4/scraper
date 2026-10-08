from scraper.models import HOUSE, LAND, Listing
from scraper.plans import Plans

DATA = """
- jls: Omišalj
  plan: PPUO Omišalj
  pravila:
    - {cestica: 500, iznimno: 400, kig: 0.3, kis: 0.6, tlocrt: 200, gbp: 400}
- jls: Omišalj
  plan: UPU Njivice
  naselja: [Njivice]
  pravila:
    - {zona: M1, od: 0, do: 600, cestica: 400, kig: 0.3, kis: 0.9}
    - {zona: M1, od: 600, cestica: 400, kig: 0.25, kis: 0.8}
    - {zona: M2, cestica: 600, kig: 0.2, kis: 0.5}
"""


def land(area):
    return Listing(source="t", source_id="1", url="u", title="Zemljište", kind=LAND, price=100_000, area=area)


def test_settlement_plan_by_zone_and_plot_size(tmp_path):
    (tmp_path / "u.yaml").write_text(DATA, encoding="utf-8")
    plans = Plans(tmp_path / "u.yaml")
    line, warning = plans.check(land(650), "Omišalj", "Njivice", zone="M1")
    assert line == "📏 UPU Njivice, M1: min. čest. 400 m² · kig 0,25 (tlocrt ≤ 162 m²) · kis 0,8 (GBP ≤ 520 m²)"
    assert not warning
    line, _ = plans.check(land(650), "Omišalj", "Njivice")          # zona nepoznata: raspon
    assert line.startswith("📏 UPU Njivice, zona nepoznata: min. čest. 400–600 m² · kig 0,2–0,25")
    # Drugo naselje: PPU općine; čestica manja od najmanje → upozorenje.
    line, warning = plans.check(land(450), "Omišalj", "Omišalj")
    assert line == "📏 PPUO Omišalj: min. čest. 500 m² · kig 0,3 (tlocrt ≤ 135 m²) · kis 0,6 (GBP ≤ 270 m²)"
    assert warning.startswith("čestica 450 m² manja je od najmanje za samostojeću kuću (500 m², PPUO Omišalj)")


def test_no_plan_or_not_land(tmp_path):
    (tmp_path / "u.yaml").write_text(DATA, encoding="utf-8")
    plans = Plans(tmp_path / "u.yaml")
    assert plans.check(land(650), "Punat", "") is None
    house = Listing(source="t", source_id="2", url="u", title="Kuća", kind=HOUSE, price=1, area=100)
    assert plans.check(house, "Omišalj", "") is None
    assert Plans(tmp_path / "nema.yaml").check(land(650), "Omišalj", "") is None


def test_caps_and_exceptions(tmp_path):
    (tmp_path / "u.yaml").write_text(DATA, encoding="utf-8")
    plans = Plans(tmp_path / "u.yaml")
    line, warning = plans.check(land(1000), "Omišalj", "")
    assert line == "📏 PPUO Omišalj: min. čest. 500 m² · kig 0,3 (tlocrt ≤ 200 m²) · kis 0,6 (GBP ≤ 400 m²)"
    _, warning = plans.check(land(420), "Omišalj", "")
    assert warning.endswith("iznimno je dopušteno od 400 m² – provjeri")
    _, warning = plans.check(land(350), "Omišalj", "")
    assert warning.endswith("(500 m², PPUO Omišalj) – provjeri")


def test_zone_from_ispu_only_where_plan_uses_it(tmp_path):
    (tmp_path / "u.yaml").write_text(DATA + """
- jls: Punat
  plan: PPUO Punat
  pravila:
    - {zona: izgrađeni dio, cestica: 450, kig: 0.25, kis: 0.75}
    - {zona: neizgrađeni dio, cestica: 450, kig: 0.25, kis: 0.6}
""", encoding="utf-8")
    plans = Plans(tmp_path / "u.yaml")
    assert plans.check(land(600), "Punat", "Punat", "neizgrađeni dio")[0] == (
        "📏 PPUO Punat, neizgrađeni dio: min. čest. 450 m² · kig 0,25 (tlocrt ≤ 150 m²) · kis 0,6 (GBP ≤ 360 m²)")
    assert "zona nepoznata" in plans.check(land(600), "Punat", "Punat")[0]
    # PPU Omišlja ne razlikuje dijelove naselja: redak bez zone.
    assert plans.check(land(600), "Omišalj", "Omišalj", "izgrađeni dio")[0].startswith("📏 PPUO Omišalj: ")


def test_real_table_loads_and_covers_all_municipalities():
    from scraper.locations import Locator

    plans = Plans()
    covered = {p.jls for p in plans.plans}
    names = {j.name for j in Locator().jls.values()}
    assert covered <= names
    assert {"Omišalj", "Krk", "Punat", "Baška", "Malinska-Dubašnica", "Vrbnik", "Dobrinj", "Opatija", "Lovran",
            "Matulji", "Rijeka", "Kostrena", "Kraljevica", "Crikvenica"} <= covered
    for p in plans.plans:
        assert p.izvor and p.url and p.pravila
        for r in p.pravila:
            assert 0 < r.kig <= 1 and (r.kis is None or 0 < r.kis <= 3)
    assert plans.find("Omišalj", "Njivice").plan.startswith("UPU Njivice")
    assert plans.find("Omišalj", "Omišalj").plan.startswith("PPUO Omišalj")
    # UPU naselja ima prednost i kad je i PPU vezan uz popis naselja (Malinska, Krk, Kraljevica).
    assert plans.find("Malinska-Dubašnica", "Malinska").plan.startswith("UPU 1 Malinska")
    assert plans.find("Kraljevica", "Šmrika").plan.startswith("UPU 23 Šmrika")
    assert plans.find("Kraljevica", "Kraljevica").plan.startswith("PPUG Kraljevica")


def test_note_ends_the_line(tmp_path):
    (tmp_path / "u.yaml").write_text("""
- jls: Baška
  plan: UPU 1 Baška
  naselja: [Baška]
  napomena: "u kulturno-povijesnoj cjelini nove kuće nisu dopuštene"
  pravila:
    - {cestica: 500, kig: 0.25, kis: 0.75, tlocrt: 150, gbp: 400}
""", encoding="utf-8")
    line, _ = Plans(tmp_path / "u.yaml").check(land(800), "Baška", "Baška")
    assert line == ("📏 UPU 1 Baška: min. čest. 500 m² · kig 0,25 (tlocrt ≤ 150 m²) · kis 0,75 (GBP ≤ 400 m²)"
                    " · u kulturno-povijesnoj cjelini nove kuće nisu dopuštene")


def test_runner_adds_rules_line_with_part_of_settlement_from_ispu(tmp_path):
    from scraper.ispu import PointInfo
    from scraper.models import PASS, WARN, Decision
    from scraper.notify import format_listing
    from scraper.runner import Runner
    from tests.test_ispu import FakeIspu

    runner = Runner(tmp_path / "s.db", tmp_path, send=False)
    runner._ispu = FakeIspu(PointInfo(gp="naselja", use="(GP) NEIZGRAĐENI DIO GRAĐEVINSKOG PODRUČJA NASELJA"))
    x = Listing(source="t", source_id="1", url="u", title="Građevinsko zemljište Punat", kind=LAND, price=150_000,
                area=600, settlement="Punat", extra={"lat": 45.02, "lon": 14.63, "priblizna_lokacija": False})
    d = Decision(PASS, jls="Punat")
    runner._check_land(x, d)
    assert x.extra["uvjeti"].startswith("📏 UPU 3 Punat (2020), neizgrađeni dio: min. čest. 450 m² · kig 0,25")
    assert d.status == PASS and "📏 UPU 3 Punat" in format_listing(x, d)
    # Bez ISPU-a (istek vremena): redak bez dijela naselja; premala čestica → ⚠.
    y = Listing(source="t", source_id="2", url="u", title="Zemljište Njivice", kind=LAND, price=90_000, area=350,
                settlement="Njivice")
    d = Decision(PASS, jls="Omišalj")
    runner._check_land(y, d, deadline=0)
    assert y.extra["uvjeti"].startswith("📏 UPU Njivice (2025): min. čest. 400 m²")
    assert d.status == WARN and d.warnings[-1].startswith("čestica 350 m² manja je od najmanje za samostojeću kuću")
    runner._check_land(y, d, deadline=0)          # neposlana obavijest, ponovna provjera: ⚠ jednom
    assert len(d.warnings) == 1


def test_dpu_note_for_settlement(tmp_path):
    (tmp_path / "u.yaml").write_text(DATA + """
- jls: Omišalj
  naselja: [Omišalj]
  dpu: [centar Omišlja, Pesja, A, B]
""", encoding="utf-8")
    plans = Plans(tmp_path / "u.yaml")
    line, _ = plans.check(land(600), "Omišalj", "Omišalj")
    assert line.endswith(" · DPU u dijelu naselja: centar Omišlja, Pesja…")
    assert "DPU" not in plans.check(land(600), "Omišalj", "Njivice")[0]


def test_dpu_without_plan_and_part_of_settlement_from_title(tmp_path):
    from scraper.models import PASS, Decision
    from scraper.runner import Runner

    plans = Plans()
    assert plans.check(land(600), "Rijeka", "Trsat")[0] == \
        "📏 DPU u dijelu naselja: Trsat, povijesna jezgra Trsata (uvjeti gradnje nisu upisani)"
    runner = Runner(tmp_path / "s.db", tmp_path, send=False)
    for jls, title, settlement, plan in [
            ("Rijeka", "Građevinsko zemljište Gornja Drenova", "Drenova", "UPU Gornja Drenova"),
            ("Rijeka", "Zemljište Drenova", "", "GUP Rijeka"),
            ("Malinska-Dubašnica", "Građevinsko zemljište Dobrinčevo", "Malinska", "UPU 3 Dobrinčevo"),
            ("Malinska-Dubašnica", "Zemljište Malinska", "Sveti Vid-Miholjice", "PPUO Malinska"),
            ("Matulji", "Zemljište Biškupi", "Matulji", "UPU 8 Biškupi"),
            ("Opatija", "Zemljište", "Strmice", "UPU Poljane"),
            ("Opatija", "Ika-Oprić građevinsko zemljište 2071 m2", "", "UPU Ika-Oprić"),
            ("Opatija", "Zemljište", "Opatija - Centar", "UPU Opatija"),
            ("Rijeka", "Zemljište Drenova", "Škurinje, Pehlin, Drenova", "GUP Rijeka (2023): min. čest. 600"),
            # Skupna lokacija portala (više mjesta, različiti planovi): plan grada/općine.
            ("Opatija", "Građevinsko zemljište Veprinac, Opatija - Okolica, Veprinac, Poljane, Opatija",
             "Veprinac, Poljane", "PPUG Opatija"),
            ("Krk", "Građevinsko zemljište, Muraj, Kornić, Lakmartin, Krk", "Muraj, Kornić, Lakmartin", "PPUG Krk"),
            ("Krk", "Građevinsko zemljište Vrh, Krk, Vrh, Pinezići, Krk", "", "PPUG Krk"),
            ("Krk", "OTOK KRK, DUNAT – Poljoprivredno zemljište", "", "PPUG Krk"),
            # nekretnine.hr: mjesto odmah iza vrste je točna lokacija (cijeli naziv).
            ("Krk", "NH Građevinsko zemljište Vrh, Krk, Vrh, Pinezići, Krk", "", "UPU 5 Vrh"),
            ("Opatija", "NH Građevinsko zemljište Dobreć, Opatija - Okolica, Vela Učka, Dobreć, Oprič", "", "UPU Dobreć"),
            ("Opatija", "NH Građevinsko zemljište Veprinac, Opatija - Okolica, Veprinac, Poljane, Opatija", "",
             "PPUG Opatija"),
            ("Rijeka", "NH Građevinsko zemljište Sušačka draga, Rijeka, Sušak, Rijeka", "", "")]:
        x = Listing(source="nekretnine_hr" if title.startswith("NH ") else "t", source_id="1", url="u",
                    title=title.removeprefix("NH "), kind=LAND, price=150_000, area=900, settlement=settlement)
        runner._building_rules(x, Decision(PASS, jls=jls))
        if not plan:
            assert "uvjeti" not in x.extra, (title, x.extra["uvjeti"])
            continue
        assert x.extra["uvjeti"].startswith(f"📏 {plan}"), (title, x.extra["uvjeti"])
        assert ("Škurinjsko" not in x.extra["uvjeti"]) and (settlement != "Škurinje, Pehlin, Drenova"
                                                          or "DPU u dijelu naselja: Drenova-Bok" in x.extra["uvjeti"])


def test_size_limits_written_as_up_to_and_including():
    """"Na čestici većoj od 1.000 m²" (Punat), "400–500 m²" (Dobrinj): granica pripada manjima."""
    plans = Plans()
    assert "tlocrt ≤ 150 m²" in plans.check(land(1000), "Punat", "Punat", "izgrađeni dio")[0]
    assert "tlocrt ≤ 200 m²" in plans.check(land(1001), "Punat", "Punat", "izgrađeni dio")[0]
    assert "kig 0,25" in plans.check(land(500), "Dobrinj", "Dobrinj")[0]
    assert "kig 0,3 " in plans.check(land(501), "Dobrinj", "Dobrinj")[0]


def test_recheck_of_unsent_notification_keeps_checked_zone_line(tmp_path):
    """Neposlana obavijest se sljedeći put ponovno provjerava: redak 🗺 iz uspjele provjere
    ostaje (i kad je vrijeme za provjere potrošeno), uz isto upozorenje."""
    from scraper.models import PASS, Decision
    from scraper.notify import format_parts
    from scraper.runner import Runner

    runner = Runner(tmp_path / "s.db", tmp_path, send=False)
    x = Listing(source="t", source_id="1", url="u", title="Građevinsko zemljište Punat", kind=LAND, price=150_000,
                area=600, municipality="Punat")
    d = Decision(PASS, jls="Punat")
    x.extra["gp"] = "🗺 Građevinsko područje: izvan građevinskog područja (k.č. 123, k.o. Punat)"
    runner._warn(d, "prema ISPU-u izvan građevinskog područja – provjeri")
    runner._check_land(x, d, deadline=0)
    text = format_parts(x, d)[0]
    assert "izvan građevinskog područja (k.č. 123" in text and "nije provjereno" not in text
