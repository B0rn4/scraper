"""Pregledni izvještaj: jedna samostalna HTML datoteka sa svim prikupljenim
oglasima, odlukom i razlogom, filterima te kvačicom "pogrešno" i gumbom
"Kopiraj označene" za prijavu grešaka."""

import html
import json
from pathlib import Path

from .models import PASS, REJECT, WARN, Decision, Listing
from .notify import SOURCE_LABELS

STATUS_ORDER = {PASS: 0, WARN: 1, REJECT: 2}


def reason_category(reason: str) -> str:
    r = reason.lower()
    if r.startswith("cijena"):
        return "cijena"
    if r.startswith("površina"):
        return "površina"
    if "lokacij" in r or "sud" in r or "županija" in r:
        return "lokacija"
    if any(w in r for w in ("dvojn", "nizu", "etaž", "dio kuće", "stan", "građevinsko", "nije kuća")):
        return "vrsta"
    return "ostalo"


def entry(listing: Listing, decision: Decision) -> dict:
    desc = " ".join(listing.description.split())
    return {
        "k": listing.key,
        "s": SOURCE_LABELS.get(listing.source, listing.source),
        "t": listing.title,
        "u": listing.url,
        "kind": "kuća" if listing.kind == "kuca" else "zemljište" if listing.kind == "zemljiste" else "ostalo",
        "sub": listing.subtype,
        "p": listing.price,
        "pp": listing.previous_price,
        "a": listing.area,
        "pa": listing.plot_area,
        "loc": ", ".join(filter(None, [listing.settlement, listing.municipality, listing.county])) or listing.location_text,
        "jls": decision.jls,
        "ev": decision.location_evidence,
        "st": decision.status,
        "r": decision.reasons,
        "w": decision.warnings,
        "cat": sorted({reason_category(r) for r in decision.reasons}),
        "nm": decision.near_miss,
        "obn": bool(listing.extra.get("za_obnovu")),
        "img": listing.image_url,
        "d": desc[:600],
        "pub": listing.published,
    }


def build(entries: list[dict], title: str, generated: str, sources: list[dict], note: str = "") -> str:
    entries = sorted(entries, key=lambda e: (STATUS_ORDER.get(e["st"], 9), not e["nm"], e["s"], e["t"]))
    data = json.dumps(entries, ensure_ascii=False).replace("</", "<\\/")
    src_rows = []
    for s in sources:
        links = " · ".join(f'<a href="{html.escape(u)}" target="_blank" rel="noopener">{html.escape(lbl)}</a>' for lbl, u in s.get("links", []))
        err = f'<div class="err">⚠ {html.escape(s["error"])}</div>' if s.get("error") else ""
        src_rows.append(
            f"<tr><td><b>{html.escape(s['label'])}</b>{err}</td><td>{s.get('total', 0)}</td>"
            f"<td>{s.get(PASS, 0)}</td><td>{s.get(WARN, 0)}</td><td>{s.get(REJECT, 0)}</td>"
            f"<td class='links'>{links or '—'}</td></tr>"
        )
    return TEMPLATE.format(
        title=html.escape(title),
        generated=html.escape(generated),
        note=f"<p class='note'>{html.escape(note)}</p>" if note else "",
        src_rows="\n".join(src_rows),
        data=data,
    )


def write(path: Path, *args, **kwargs) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build(*args, **kwargs), encoding="utf-8")
    return path


TEMPLATE = """<!doctype html>
<html lang="hr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{ --bg:#f6f7f9; --card:#fff; --text:#1d2330; --muted:#667085; --line:#e4e7ec;
  --pass:#12805c; --warn:#b54708; --rej:#b42318; --accent:#175cd3; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#111418; --card:#1b2027; --text:#e6e8eb; --muted:#9aa4b2;
  --line:#2c333d; --pass:#47cd89; --warn:#fdb022; --rej:#f97066; --accent:#84adff; }} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; font:15px/1.45 -apple-system,Segoe UI,Roboto,sans-serif; background:var(--bg); color:var(--text); }}
header {{ padding:16px; }}
h1 {{ font-size:20px; margin:0 0 4px; }}
.muted {{ color:var(--muted); font-size:13px; }}
.note {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:10px 12px; }}
table {{ border-collapse:collapse; width:100%; font-size:13px; background:var(--card); border-radius:10px; overflow:hidden; }}
th,td {{ text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); vertical-align:top; }}
td.links a {{ color:var(--accent); }}
.err {{ color:var(--rej); font-size:12px; }}
.wrap {{ overflow-x:auto; }}
.bar {{ position:sticky; top:0; z-index:5; background:var(--bg); border-bottom:1px solid var(--line); padding:10px 16px; display:flex; flex-wrap:wrap; gap:8px; align-items:center; }}
.chip {{ display:inline-flex; gap:4px; align-items:center; border:1px solid var(--line); background:var(--card); border-radius:999px; padding:4px 10px; font-size:13px; cursor:pointer; user-select:none; }}
.chip input {{ margin:0; }}
select,input[type=search] {{ font:inherit; font-size:14px; padding:5px 8px; border:1px solid var(--line); border-radius:8px; background:var(--card); color:var(--text); }}
input[type=search] {{ flex:1 1 160px; min-width:0; }}
main {{ padding:12px 16px 90px; display:grid; gap:10px; grid-template-columns:repeat(auto-fill,minmax(320px,1fr)); }}
.card {{ background:var(--card); border:1px solid var(--line); border-left:5px solid var(--line); border-radius:10px; padding:10px; display:flex; gap:10px; }}
.card.prolazi {{ border-left-color:var(--pass); }} .card.upozorenje {{ border-left-color:var(--warn); }} .card.odbijen {{ border-left-color:var(--rej); }}
.card.marked {{ outline:2px solid var(--accent); }}
.card img {{ width:96px; height:72px; object-fit:cover; border-radius:6px; flex:none; background:var(--line); }}
.body {{ min-width:0; flex:1; }}
.t {{ font-weight:600; font-size:14px; margin:0 0 2px; overflow-wrap:anywhere; }}
.t a {{ color:inherit; }}
.facts {{ font-size:13px; }}
.st {{ font-size:12px; font-weight:700; }}
.st.prolazi {{ color:var(--pass); }} .st.upozorenje {{ color:var(--warn); }} .st.odbijen {{ color:var(--rej); }}
.reason {{ font-size:12px; margin-top:2px; }}
.reason.r {{ color:var(--rej); }} .reason.w {{ color:var(--warn); }}
details {{ font-size:12px; color:var(--muted); margin-top:4px; }}
.mark {{ display:flex; gap:6px; align-items:center; margin-top:6px; font-size:13px; }}
.mark input[type=text] {{ flex:1; min-width:0; font:inherit; font-size:12px; padding:3px 6px; border:1px solid var(--line); border-radius:6px; background:var(--bg); color:var(--text); }}
.more {{ grid-column:1/-1; text-align:center; }}
button {{ font:inherit; font-size:14px; padding:8px 14px; border-radius:8px; border:1px solid var(--accent); background:var(--accent); color:#fff; cursor:pointer; }}
button.ghost {{ background:transparent; color:var(--accent); }}
.foot {{ position:fixed; left:0; right:0; bottom:0; background:var(--card); border-top:1px solid var(--line); padding:10px 16px; display:flex; gap:10px; align-items:center; justify-content:space-between; z-index:6; }}
textarea#out {{ position:fixed; left:-9999px; }}
</style>
</head>
<body>
<header>
  <h1>{title}</h1>
  <div class="muted">Izrađeno: {generated}</div>
  {note}
  <div class="wrap"><table>
    <tr><th>Izvor</th><th>Ukupno</th><th>✅</th><th>⚠</th><th>❌</th><th>Ista pretraga na portalu (za usporedbu)</th></tr>
    {src_rows}
  </table></div>
</header>
<div class="bar">
  <label class="chip"><input type="checkbox" class="f-st" value="prolazi" checked>✅ prolazi</label>
  <label class="chip"><input type="checkbox" class="f-st" value="upozorenje" checked>⚠ upozorenje</label>
  <label class="chip"><input type="checkbox" class="f-st" value="odbijen" checked>❌ odbijen</label>
  <label class="chip"><input type="checkbox" id="f-nm">samo za dlaku</label>
  <select id="f-cat"><option value="">svi razlozi</option><option>lokacija</option><option>cijena</option><option>površina</option><option>vrsta</option><option>ostalo</option></select>
  <select id="f-src"><option value="">svi izvori</option></select>
  <select id="f-kind"><option value="">kuće i zemljišta</option><option value="kuća">kuće</option><option value="zemljište">zemljišta</option></select>
  <input type="search" id="f-q" placeholder="Traži (naslov, mjesto, razlog)…">
  <span class="muted" id="count"></span>
</div>
<main id="list"></main>
<div class="foot">
  <span id="marked">Označeno: 0</span>
  <span><button class="ghost" id="clear">Poništi</button> <button id="copy">Kopiraj označene</button></span>
</div>
<textarea id="out"></textarea>
<script>
const DATA = {data};
const PAGE = 200;
let shown = PAGE;
const marked = new Map();
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}})[c]);
const eur = v => v ? Math.round(v).toLocaleString("hr-HR") + " €" : "—";
const m2 = v => v ? Math.round(v).toLocaleString("hr-HR") + " m²" : "—";
const LABEL = {{prolazi:"✅ prolazi", upozorenje:"⚠ upozorenje", odbijen:"❌ odbijen"}};
[...new Set(DATA.map(e => e.s))].sort().forEach(s => $("#f-src").insertAdjacentHTML("beforeend", `<option>${{esc(s)}}</option>`));

function filtered() {{
  const st = [...document.querySelectorAll(".f-st:checked")].map(x => x.value);
  const nm = $("#f-nm").checked, cat = $("#f-cat").value, src = $("#f-src").value, kind = $("#f-kind").value;
  const q = $("#f-q").value.trim().toLowerCase();
  return DATA.filter(e => st.includes(e.st) && (!nm || e.nm) && (!cat || e.cat.includes(cat)) && (!src || e.s === src)
    && (!kind || e.kind === kind)
    && (!q || [e.t, e.loc, e.jls, e.sub, ...e.r, ...e.w].join(" ").toLowerCase().includes(q)));
}}

function card(e, i) {{
  const m = marked.get(e.k);
  const price = e.pp && e.p && e.pp > e.p ? `${{eur(e.p)}} <span class="muted">(prije ${{eur(e.pp)}})</span>` : eur(e.p);
  return `<article class="card ${{e.st}} ${{m ? "marked" : ""}}">
    ${{e.img ? `<img loading="lazy" src="${{esc(e.img)}}" alt="">` : ""}}
    <div class="body">
      <div class="st ${{e.st}}">${{LABEL[e.st]}}${{e.nm ? " · za dlaku" : ""}}${{e.obn ? " · 🔨 za obnovu" : ""}}</div>
      <p class="t"><a href="${{esc(e.u)}}" target="_blank" rel="noopener">${{esc(e.t)}}</a></p>
      <div class="facts">${{esc(e.kind)}}${{e.sub ? " · " + esc(e.sub) : ""}} · ${{price}} · ${{m2(e.a)}}${{e.pa ? " · okućnica " + m2(e.pa) : ""}}</div>
      <div class="facts muted">📍 ${{esc(e.loc)}} → <b>${{esc(e.jls || "?")}}</b> · ${{esc(e.s)}}</div>
      ${{e.r.map(r => `<div class="reason r">❌ ${{esc(r)}}</div>`).join("")}}
      ${{e.w.map(w => `<div class="reason w">⚠ ${{esc(w)}}</div>`).join("")}}
      ${{e.d ? `<details><summary>opis</summary>${{esc(e.d)}}</details>` : ""}}
      <div class="mark"><label><input type="checkbox" data-i="${{i}}" class="m" ${{m ? "checked" : ""}}> pogrešno</label>
        <input type="text" data-i="${{i}}" class="n" placeholder="napomena (npr. trebao je proći)" value="${{esc(m ? m.note : "")}}" ${{m ? "" : "hidden"}}></div>
    </div></article>`;
}}

let current = [];
function render(reset) {{
  if (reset) shown = PAGE;
  current = filtered();
  $("#count").textContent = `${{current.length}} od ${{DATA.length}}`;
  const html = current.slice(0, shown).map((e, i) => card(e, i)).join("");
  $("#list").innerHTML = html + (current.length > shown ? `<div class="more"><button class="ghost" id="more">Prikaži još (${{current.length - shown}})</button></div>` : "");
  const more = $("#more"); if (more) more.onclick = () => {{ shown += PAGE; render(false); }};
}}

$("#list").addEventListener("change", ev => {{
  const t = ev.target, e = current[+t.dataset.i];
  if (!e) return;
  if (t.classList.contains("m")) {{
    if (t.checked) marked.set(e.k, {{e, note: ""}}); else marked.delete(e.k);
    t.closest(".card").classList.toggle("marked", t.checked);
    const n = t.closest(".mark").querySelector(".n"); n.hidden = !t.checked; if (t.checked) n.focus();
  }}
  $("#marked").textContent = `Označeno: ${{marked.size}}`;
}});
$("#list").addEventListener("input", ev => {{
  const t = ev.target; if (!t.classList.contains("n")) return;
  const e = current[+t.dataset.i]; if (marked.has(e.k)) marked.get(e.k).note = t.value;
}});
document.querySelectorAll(".bar input, .bar select").forEach(el => el.addEventListener("input", () => render(true)));
$("#clear").onclick = () => {{ marked.clear(); $("#marked").textContent = "Označeno: 0"; render(false); }};
$("#copy").onclick = async () => {{
  if (!marked.size) {{ alert("Nema označenih oglasa."); return; }}
  const lines = [...marked.values()].map(({{e, note}}) =>
    `[${{e.st}}] ${{e.k}} | ${{e.t}} | ${{eur(e.p)}} | ${{m2(e.a)}} | ${{e.loc}} → ${{e.jls || "?"}} | ${{[...e.r, ...e.w].join("; ") || "bez napomena"}}${{note ? " | NAPOMENA: " + note : ""}} | ${{e.u}}`);
  const text = "Pogrešno označeni oglasi ({title}):\\n" + lines.join("\\n");
  try {{ await navigator.clipboard.writeText(text); }}
  catch (_) {{ const ta = $("#out"); ta.value = text; ta.select(); document.execCommand("copy"); }}
  alert(`Kopirano (${{marked.size}}). Zalijepi u razgovor s Claudeom.`);
}};
render(true);
</script>
</body>
</html>
"""
