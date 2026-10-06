"""Popis svih praćenih stranica na jednom mjestu (HTML), za ručnu provjeru propuštenih oglasa.

Poveznice dolaze iz istog koda koji čita portale (search_links, s filtrima iz kriterija),
iz data/natjecaji.yaml i data/banke.yaml, pa se popis ne mora ručno održavati.
Pokretanje: python tools/stranice.py izlaz.html"""

import html
import sys
from pathlib import Path
from urllib.parse import urlparse

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.locations import Locator  # noqa: E402
from scraper.runner import load_config  # noqa: E402
from scraper.sources import ALL  # noqa: E402
from scraper.text import fmt_eur, fmt_m2  # noqa: E402
from scraper.watch import load_pages  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"
# Kako i koliko često scraper čita portal (za čitatelja, ne za kod).
HOW = {
    "nekretnine_hr": ("svakih 20 min", "najnoviji i nedavno izmijenjeni oglasi cijele PGŽ; isti oglasi kao Crozilla i Indomio"),
    "index_oglasi": ("svakih 20 min", "najnoviji oglasi, naših 14 gradova i općina"),
    "oglasnik": ("svakih 20 min", "najnoviji oglasi PGŽ"),
    "vender": ("svakih 20 min", "najnoviji oglasi PGŽ"),
    "njuskalo": ("svakih 20 min, s Redmija", "najnoviji oglasi PGŽ; stari oglasi koje agencije ponovno objave ne stižu"),
    "realestatecroatia": ("svakih 20 min", "oglasi agencija iz sustava Agentor, najnoviji prvi"),
    "burza": ("svakih 20 min", "regija Kvarner i Istra; oglasi izvan PGŽ-a se odbijaju"),
    "fina": ("jednom dnevno", "sudske prodaje (Očevidnik), samo građevinska zemljišta"),
}
SKIPPED = [
    ("GoHome", "https://www.gohome.hr/", "tražilica tuđih oglasa: ~95 % oglasa agencija već je na našim portalima, kasni 0–3 dana"),
    ("Realitica", "https://www.realitica.com/", "49 od 50 najnovijih oglasa već je na index.hr, nekretnine.hr ili oglasnik.hr"),
    ("nekretnine24.hr", "https://www.nekretnine24.hr/", "nema oglasa za naše područje"),
    ("oglasi.hr", "https://www.oglasi.hr/", "gotovo prazan"),
    ("trazimstan.hr", "https://www.trazimstan.hr/", "većinom najam"),
    ("Stranice agencija", "", "iza Cloudflareove zaštite; većina oglasa ide kroz realestatecroatia.com"),
    ("Facebook grupe i Marketplace", "", "ručno: u lokalnim grupama uključi obavijesti „Sve objave”"),
]


def human_url(site: dict) -> str:
    """Stranica koju čovjek otvara: WordPress i RSS → pretraga stranice za "prodaj"."""
    url = site["url"]
    if site.get("nacin") in ("wp", "rss"):
        return url.rstrip("/") + "/?s=prodaj"
    if site.get("nacin") == "feed":
        p = urlparse(url)
        return f"{p.scheme}://{p.netloc}/"
    return url


def e(text) -> str:
    return html.escape(str(text), quote=True)


def row(key: str, name: str, meta: str, note: str, links: list[tuple[str, str]]) -> str:
    buttons = "".join(f'<a class="go" href="{e(u)}" target="_blank" rel="noopener">{e(label)}</a>' for label, u in links)
    return f"""<li class="row" data-key="{e(key)}">
  <div class="what"><h3>{e(name)}</h3>
    <p class="meta"><span class="when">{e(meta)}</span>{f' · {e(note)}' if note else ''}</p></div>
  <div class="links">{buttons}</div>
  <label class="seen"><input type="checkbox" id="seen-{e(key)}"><span>pregledano</span><time></time></label>
</li>"""


def build() -> str:
    cfg = load_config()
    crit = cfg["kriteriji"]
    locator = Locator()
    places = sorted(j.name for j in locator.jls.values() if j.included)

    portals = []
    for name, cls in ALL.items():
        where = cfg["izvori"].get(name)
        if not where:
            continue
        src = cls(None, locator, crit)
        when, note = HOW.get(name, ("", ""))
        portals.append(row(f"p-{name}", src.label, when, note, src.search_links()))

    tenders, region = [], []
    for site in yaml.safe_load((DATA / "natjecaji.yaml").read_text(encoding="utf-8")):
        item = row(f"n-{site['naziv']}", site["naziv"], "jednom dnevno",
                   "pretraga stranice za „prodaj”" if site.get("nacin") in ("wp", "rss") else "",
                   [("otvori", human_url(site))])
        (tenders if site.get("jls") else region).append(item)

    banks = [row(f"b-{p['naziv']}", p["naziv"], "jednom dnevno",
                 "mail kod svake promjene" if p.get("svaka_promjena") else "poruka kad se pojavi naše mjesto",
                 [("otvori", p["url"])]) for p in load_pages()]

    def skipped_item(name, url, why):
        title = f'<a href="{e(url)}" target="_blank" rel="noopener">{e(name)}</a>' if url else e(name)
        return f"<li><b>{title}</b> – {e(why)}</li>"

    skipped = "".join(skipped_item(*s) for s in SKIPPED)
    k, z = crit["kuca"], crit["zemljiste"]
    criteria = (f"<li><b>Kuće</b> do {e(fmt_eur(k['max_cijena']))}, od {e(fmt_m2(k['min_povrsina']))} stambene površine</li>"
                f"<li><b>Građevinska zemljišta</b> do {e(fmt_eur(z['max_cijena']))}, od {e(fmt_m2(z['min_povrsina']))}</li>"
                f"<li><b>Područje</b>: {e(', '.join(places))} – uz odluke po naseljima iz tvog popisa</li>")
    return TEMPLATE.format(criteria=criteria, portals="\n".join(portals), tenders="\n".join(tenders),
                           region="\n".join(region), banks="\n".join(banks), skipped=skipped,
                           n_portals=len(portals), n_tenders=len(tenders) + len(region), n_banks=len(banks))


TEMPLATE = """<title>Praćeni oglasnici i natječaji</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow:wght@400;500;600&family=Barlow+Condensed:wght@500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
/* Imenik s provjerom: po skupini popis redaka, svaki redak = izvor, poveznice i oznaka "pregledano". */
:root {{
  --bg: #f3f6f6; --surface: #ffffff; --ink: #14232a; --muted: #56686f; --line: #d5dfe1;
  --accent: #0b6a78; --accent-ink: #ffffff; --ok: #2c7a4b; --ok-bg: #e3f1e8;
  --display: "Barlow Condensed", "Arial Narrow", sans-serif; --body: "Barlow", system-ui, sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, monospace;
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --bg: #0e171b; --surface: #152127; --ink: #e2ebed; --muted: #94a7ae; --line: #27383f;
  --accent: #4db0bf; --accent-ink: #062126; --ok: #7ccf9a; --ok-bg: #173226; color-scheme: dark }} }}
:root[data-theme="dark"] {{
  --bg: #0e171b; --surface: #152127; --ink: #e2ebed; --muted: #94a7ae; --line: #27383f;
  --accent: #4db0bf; --accent-ink: #062126; --ok: #7ccf9a; --ok-bg: #173226; color-scheme: dark }}
body {{ background: var(--bg); color: var(--ink); font: 16px/1.5 var(--body); }}
.page {{ max-width: 980px; margin: 0 auto; padding-inline: 16px; padding-block: 28px 56px; display: grid; gap: 32px; }}
header {{ display: grid; gap: 12px; }}
h1 {{ font: 600 2.2rem/1.1 var(--display); letter-spacing: .01em; margin: 0; text-wrap: balance; }}
h2 {{ font: 600 1.35rem/1.2 var(--display); letter-spacing: .03em; text-transform: uppercase; margin: 0; }}
h3 {{ font: 600 1.05rem/1.3 var(--body); margin: 0; }}
p {{ margin: 0; max-width: 68ch; }}
.lead {{ color: var(--muted); }}
.criteria {{ margin: 0; padding: 14px 18px; list-style: none; display: grid; gap: 4px; background: var(--surface);
  border: 1px solid var(--line); border-radius: 6px; }}
.howto {{ display: grid; gap: 6px; padding-left: 1.2em; margin: 0; color: var(--ink); }}
.howto li::marker {{ color: var(--accent); font-family: var(--mono); }}
section {{ display: grid; gap: 12px; }}
.sechead {{ display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 8px;
  border-bottom: 2px solid var(--ink); padding-bottom: 6px; }}
.count {{ font: 500 .8rem var(--mono); color: var(--muted); }}
ul.rows {{ list-style: none; margin: 0; padding: 0; display: grid; }}
.row {{ display: grid; grid-template-columns: minmax(0, 1fr) auto; grid-template-areas: "what seen" "links links";
  gap: 8px 16px; padding: 12px 0; border-bottom: 1px solid var(--line); }}
.what {{ grid-area: what; min-width: 0; display: grid; gap: 2px; }}
.meta {{ font-size: .9rem; color: var(--muted); }}
.when {{ font: 500 .78rem var(--mono); letter-spacing: .02em; color: var(--accent); }}
.links {{ grid-area: links; display: flex; flex-wrap: wrap; gap: 6px; }}
.go {{ display: inline-block; padding: 5px 10px; border: 1px solid var(--accent); border-radius: 4px; color: var(--accent);
  text-decoration: none; font-size: .88rem; line-height: 1.3; overflow-wrap: anywhere; }}
.go:hover {{ background: var(--accent); color: var(--accent-ink); }}
.go:focus-visible, .seen input:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 2px; }}
.seen {{ grid-area: seen; display: flex; align-items: center; gap: 6px; font-size: .82rem; color: var(--muted); cursor: pointer;
  white-space: nowrap; align-self: start; }}
.seen input {{ width: 18px; height: 18px; accent-color: var(--ok); }}
.seen time {{ font-family: var(--mono); font-size: .75rem; }}
.row.done .seen {{ color: var(--ok); }}
.row.done h3::after {{ content: " ✓"; color: var(--ok); }}
.subhead {{ font: 500 .78rem var(--mono); text-transform: uppercase; letter-spacing: .06em; color: var(--muted); margin-top: 8px; }}
.skipped {{ margin: 0; padding-left: 1.1em; display: grid; gap: 4px; color: var(--muted); }}
.skipped a, .skipped b {{ color: var(--ink); }}
.tools {{ display: flex; justify-content: flex-end; }}
button.reset {{ font: inherit; font-size: .85rem; padding: 6px 12px; border-radius: 4px; border: 1px solid var(--line);
  background: var(--surface); color: var(--ink); cursor: pointer; }}
@media (max-width: 560px) {{ .row {{ grid-template-columns: 1fr; grid-template-areas: "what" "links" "seen"; }} }}
</style>
<div class="page">
<header>
  <h1>Praćeni oglasnici i natječaji</h1>
  <p class="lead">Sve stranice koje scraper čita, s poveznicama na iste pretrage na portalu. Otvori, prođi oglase s našeg
  područja i usporedi s onim što je stiglo na Telegram.</p>
  <ul class="criteria">{criteria}</ul>
  <ul class="howto">
    <li>Poveznice portala već imaju filtar cijene (i površine gdje portal to podržava) i najnovije oglase na vrhu.</li>
    <li>Ako nađeš oglas koji odgovara, a nije stigao ni kao ⚠, pošalji mi poveznicu – to je propust koji treba popraviti.</li>
    <li>Ne stižu namjerno: oglas već poslan s drugog portala, stari oglas koji agencija ponovno objavi, naselja koja si
    u popisu označio da ne stižu, oglasi označeni s 🔕 Ne zanima me i stanovi. „Cijena na upit” stiže s ⚠ i procjenom,
    osim luksuznih i golemih (procjena daleko iznad granice) te s realestatecroatia.com i burze.</li>
    <li>Oznaka „pregledano” pamti se samo u ovom pregledniku.</li>
  </ul>
</header>

<section>
  <div class="sechead"><h2>Oglasnici</h2><span class="count">{n_portals} izvora</span></div>
  <ul class="rows">{portals}</ul>
</section>

<section>
  <div class="sechead"><h2>Natječaji za prodaju</h2><span class="count">{n_tenders} stranica · jednom dnevno</span></div>
  <p class="subhead">Gradovi i općine</p>
  <ul class="rows">{tenders}</ul>
  <p class="subhead">Županija i država</p>
  <ul class="rows">{region}</ul>
</section>

<section>
  <div class="sechead"><h2>Banke i preuzete nekretnine</h2><span class="count">{n_banks} stranica · jednom dnevno</span></div>
  <ul class="rows">{banks}</ul>
</section>

<section>
  <div class="sechead"><h2>Ne pratimo</h2><span class="count">provjereno i izostavljeno</span></div>
  <ul class="skipped">{skipped}</ul>
</section>

<div class="tools"><button class="reset" id="reset" type="button">Očisti oznake „pregledano”</button></div>
</div>
<script>
(function () {{
  var KEY = "pracene-stranice-pregledano";
  function load() {{ try {{ return JSON.parse(localStorage.getItem(KEY) || "{{}}"); }} catch (e) {{ return {{}}; }} }}
  function save(v) {{ try {{ localStorage.setItem(KEY, JSON.stringify(v)); }} catch (e) {{}} }}
  var state = load();
  function paint(row) {{
    var k = row.dataset.key, box = row.querySelector("input"), t = row.querySelector("time");
    box.checked = !!state[k]; row.classList.toggle("done", !!state[k]);
    t.textContent = state[k] ? new Date(state[k]).toLocaleDateString("hr-HR") : "";
  }}
  document.querySelectorAll(".row").forEach(function (row) {{
    paint(row);
    row.querySelector("input").addEventListener("change", function (ev) {{
      if (ev.target.checked) state[row.dataset.key] = Date.now(); else delete state[row.dataset.key];
      save(state); paint(row);
    }});
  }});
  document.getElementById("reset").addEventListener("click", function () {{
    state = {{}}; save(state); document.querySelectorAll(".row").forEach(paint);
  }});
}})();
</script>
"""


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "stranice.html")
    out.write_text(build(), encoding="utf-8")
    print(out)
