from scraper import planwatch
from scraper.db import State

SN_PAGE = """<table>
<tr><td><a href="default.asp?Link=odluke&amp;id=51700">Odluka o donošenju II. izmjena i dopuna Urbanističkog plana
 uređenja UPU 2 – Njivice (NA1)</a></td></tr>
<tr><td><a href="default.asp?Link=odluke&amp;id=51701">Odluka o komunalnom redu</a></td></tr>
<tr><td><a href="default.asp?Link=odluke&amp;id=51702">Odluka o izboru članova Odbora za prostorno planiranje</a></td></tr>
<tr><td><a href="default.asp?Link=odluke&amp;id=51703">Odluka o izradi izmjena i dopuna Prostornog plana uređenja
 Općine Omišalj</a></td></tr>
</table>"""

REGISTRY = """<table>
<tr id="plan-1"><td><span>Grad/Opcina:</span><div>Crikvenica</div></td>
<td class="strong"><span>Broj sluzbenog glasila:</span><div><a href="https://zavod.pgz.hr/sn_jls/Crikvenica/2026_270_1900_donosenje.pdf"
 target="_blank">2026-270</a></div></td>
<td><span>Naziv plana:</span><div class="namePlan">Odluka o donošenju III. izmjena i dopuna UPU Dramalj centar</div></td>
<td class="lastRow"><div>Donesen</div></td></tr>
<tr><td>Grad Bakar</td><td>PPU</td><td><a href="/sn_jls/Bakar/2026_10_1901_donosenje.pdf">2026-10</a></td></tr>
<tr><td>Općina Moščenička Draga</td><td>UPU 3</td><td><a href="/sn_jls/Moscenicka_Draga/2026_5_1902_izrada.pdf">x</a></td></tr>
<tr><td>Općina Malinska-Dubašnica</td><td>PPUO</td><td><a href="/sn_jls/Malinska_Dubasnica/2026_5_1903_izrada.pdf">x</a></td></tr>
</table>"""


def test_sn_page_keeps_only_plan_decisions():
    found = planwatch.sn_decisions(SN_PAGE, "Omišalj", "https://www.sn.pgz.hr/default.asp?Link=popis&sifra=51513")
    assert [d.url.rsplit("=", 1)[1] for d in found] == ["51700", "51703"]
    assert found[0].title.startswith("Odluka o donošenju II. izmjena i dopuna Urbanističkog plana uređenja UPU 2")
    assert found[0].url == "https://www.sn.pgz.hr/default.asp?Link=odluke&id=51700"


def test_registry_only_our_municipalities_with_row_text():
    found = planwatch.registry_decisions(REGISTRY, "https://zavod.pgz.hr/Home.aspx?pagename=Registarprostornihplanova")
    assert [(d.jls, d.url.rsplit("/", 1)[1]) for d in found] == [
        ("Crikvenica", "2026_270_1900_donosenje.pdf"), ("Malinska-Dubašnica", "2026_5_1903_izrada.pdf")]
    assert found[0].title == "Odluka o donošenju III. izmjena i dopuna UPU Dramalj centar (glasilo 2026-270)"
    assert found[1].title.startswith("odluka o izradi – ")


def test_first_read_of_a_source_is_silent_then_new_ones_reported(tmp_path):
    pages = {"sn": SN_PAGE, "reg": REGISTRY}

    def get(url):
        if "zavod" in url:
            return pages["reg"]
        if "sifra=51513" in url:
            return pages["sn"]
        if "sifra=51500" in url:
            raise OSError("mreža")
        return ""

    state = State(tmp_path / "s.db")
    first = planwatch.check(get, state, 2026)
    assert first.new == [] and first.known == 4 and first.errors == ["Službene novine PGŽ, Krk: OSError"] * 2
    assert planwatch.check(get, state, 2026).new == []          # nije spremljeno: opet "prvo čitanje"
    first.save(state)
    pages["sn"] += '<a href="default.asp?Link=odluke&id=51800">Odluka o donošenju UPU 1 Omišalj</a>'
    pages["reg"] += '<tr><td>Kostrena</td><td>UPU N-5</td><td><a href="/sn_jls/Kostrena/2026_9_1950_donosenje.pdf">a</a></td></tr>'
    second = planwatch.check(get, state, 2026)
    assert [(d.jls, d.title[:30]) for d in second.new] == [("Omišalj", "Odluka o donošenju UPU 1 Omiša"),
                                                         ("Kostrena", "Kostrena UPU N-5 a")]
    second.save(state)
    assert planwatch.check(get, state, 2026).new == []
    state.close()


def test_weekly_section_text():
    from scraper.runner import Runner

    res = planwatch.Result([planwatch.PlanDecision("Omišalj", "Odluka o donošenju UPU 1 Omišalj", "https://x/1")],
                           7, ["Registar Zavoda: OSError"], {})
    text = Runner._plan_section(res)
    assert "Omišalj: <a href='https://x/1'>Odluka o donošenju UPU 1 Omišalj</a>" in text
    assert "uvjeti_gradnje.yaml" in text and "Nije provjereno: Registar Zavoda: OSError" in text
    assert "Nijedna (praćeno 7 odluka" in Runner._plan_section(planwatch.Result([], 7, [], {}))
    assert "Provjera nije uspjela" in Runner._plan_section(None)


def test_weekly_remembers_decisions_only_when_mail_sent(tmp_path):
    from scraper.runner import Runner

    class Mail:
        ok = False

        def send(self, subject, *a, **k):
            if not self.ok:
                raise OSError("SMTP")

    r = Runner(tmp_path / "s.db", tmp_path, send=False)
    r.email = Mail()
    r._plan_decisions = lambda: planwatch.Result([], 1, [], {planwatch.SEEN_KEY: '["https://x/1"]'})
    assert r.weekly(record=False) is False
    state = State(tmp_path / "s.db")
    assert state.meta_get(planwatch.SEEN_KEY) is None
    r.email.ok = True
    assert r.weekly(record=False) is True
    assert state.meta_get(planwatch.SEEN_KEY) == '["https://x/1"]'
    state.close()
