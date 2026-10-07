import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import build_ppv  # noqa: E402
from scraper.ispu import to_htrs  # noqa: E402
from scraper.locations import Locator  # noqa: E402


def block(name, grop, *rows, use="IZGRAĐENI DIO GRAĐEVINSKOG PODRUČJA NASELJA", code="GP", xy=None):
    b = {"cb_naziv": name, "ppv_cb_grop": grop, "cb_opis_namjene": use, "cb_oznaka_namjene": code}
    for i, (kind, nz, value) in enumerate(rows, 1):
        b.update({f"ppv_vn_{i}": kind, f"ppv_nz_{i}": nz, f"ppv_pv_eu_{i}": value})
    if xy:
        b["_x"], b["_y"] = xy
    return b


GZ = "Građevinsko zemljište (GZ)"


def test_block_places():
    assert build_ppv.block_places("BRUSIĆI, BAJČIĆI, POLJICA - ŠUMA") == ["brusici", "bajcici", "poljica"]
    assert build_ppv.block_places("NJIVICE - GRAĐEVINSKO 2") == ["njivice"]
    assert build_ppv.block_places("SVETI VID - MIHOLJICE - OSTALO TLO") == build_ppv.block_places("Sveti Vid-Miholjice - X")


def test_median_of_all_residential_values_and_building_blocks_first():
    blocks = [
        block("NJIVICE - GRAĐEVINSKO", None, (GZ, "S", 158.3), (GZ, "M2", 218.7)),       # bez grada/općine
        block("NJIVICE - GRAĐEVINSKO 2", "OMIŠALJ", (GZ, "GP-IZGRAĐENO", 188), (GZ, "K1", 400)),  # K1 nije stambena
        block("NJIVICE - OBRADIVO TLO I ŠUME", "OMIŠALJ", ("Poljoprivredno zemljište (PZ)", "P2", 20), (GZ, "GP", 30),
              use="OSOBITO VRIJEDNO OBRADIVO TLO", code="P2"),                       # nije blok građevinskog područja
        block("VELI DOL - VRIJEDNO OBRADIVO TLO", "KRALJEVICA", (GZ, "GP", 33), use="OBRADIVO TLO", code="P2"),
        block("KASTAV - GRAĐEVINSKO", "KASTAV", (GZ, "S", 500)),                       # nije naš grad
    ]
    out = build_ppv.build(blocks, Locator(), "2026")
    assert out["naselja"]["Omišalj"]["njivice"] == {"zemljiste": [158, 219], "medijan": 188, "blokova": 2}
    assert out["naselja"]["Kraljevica"]["veli dol"]["medijan"] == 33       # samo ostali blokovi: uzimaju se
    assert out["gradovi_opcine"]["Omišalj"] == {"zemljiste": [158, 219], "medijan": 188, "naselja": 1, "blokova": 2}
    assert "Kastav" not in out["naselja"] and out["godina"] == 2026


def test_same_name_in_two_municipalities_goes_to_nearest_settlement():
    from types import SimpleNamespace as NS

    loc = NS(jls={"a": NS(name="Grad A", included=True, settlements=["Draga"], extra=[]),
                  "b": NS(name="Općina B", included=True, settlements=["Draga", "Polje"], extra=[])})
    rows = [{"naselje": "Draga", "jls": "Grad A", "lat": 45.30, "lon": 14.40},
            {"naselje": "Draga", "jls": "Općina B", "lat": 45.05, "lon": 14.60}]
    near_b = block("DRAGA - GRAĐEVINSKO", None, (GZ, "S", 100), xy=to_htrs(45.051, 14.601))
    near_a = block("DRAGA - GRAĐEVINSKO 2", None, (GZ, "S", 300), xy=to_htrs(45.301, 14.401))
    out = build_ppv.build([near_b, near_a], loc, "2026", rows)
    assert out["naselja"]["Općina B"]["draga"]["medijan"] == 100
    assert out["naselja"]["Grad A"]["draga"]["medijan"] == 300


def test_hamlet_without_own_block_gets_block_around_its_centre():
    from types import SimpleNamespace as NS

    loc = NS(jls={"k": NS(name="Kostrena", included=True, settlements=["Kostrena", "Paveki", "Glavani"], extra=[])})
    x, y = to_htrs(45.30, 14.50)
    square = [[x - 500, y - 500], [x + 500, y - 500], [x + 500, y + 500], [x - 500, y + 500]]
    main = block("KOSTRENA - GRAĐEVINSKO 1", "KOSTRENA", (GZ, "S", 150), (GZ, "M1", 170))
    main["_obris"] = [square]
    rows = [{"naselje": "Paveki", "jls": "Kostrena", "lat": 45.30, "lon": 14.50},
            {"naselje": "Glavani", "jls": "Kostrena", "lat": 45.40, "lon": 14.60}]       # izvan bloka
    out = build_ppv.build([main], loc, "2026", rows)
    assert out["naselja"]["Kostrena"] == {"kostrena": {"zemljiste": [150, 170], "medijan": 160, "blokova": 1},
                                         "paveki": {"zemljiste": [150, 170], "medijan": 160, "blokova": 1}}
    assert out["gradovi_opcine"]["Kostrena"]["blokova"] == 1                     # isti blok jednom
