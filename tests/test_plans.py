from scraper.models import HOUSE, LAND, Listing
from scraper.plans import Plans

DATA = """
- jls: Omišalj
  plan: PPUO Omišalj
  pravila:
    - {cestica: 500, kig: 0.3, kis: 0.6}
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
    assert line == "📏 UPU Njivice, zona M1: min. čest. 400 m² · kig 0,25 (tlocrt ≤ 162 m²) · kis 0,8 (GBP ≤ 520 m²)"
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
