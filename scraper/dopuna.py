"""Dopuna s preciznijeg portala (odluka korisnika 8. 10.).

Kad poslani oglas kasnije stigne i s drugog portala (isti oglas, vidi dedupe.py), a taj zna
nešto više, stiže kratka poruka kao odgovor na prvu: samo gumb za oglas i popis onoga što je
novo, bez ponavljanja ostatka obavijesti:
- lokacija i građevinsko područje: bolja lokacija (broj čestice > točna oznaka > krug oko
  približne oznake > ništa) donosi redak 🗺, PPV na lokaciji i 📏 uvjete gradnje;
- podaci koji su nedostajali: naselje, vrsta kuće, okućnica, godina izgradnje / obnove,
  vlasnički list, parking, „za obnovu”, parcelacija;
- nova upozorenja iz opisa (i s ISPU-a na boljoj lokaciji);
- ⚠ kad prema novom portalu oglas ne odgovara kriterijima (npr. „nije građevinsko”).
Dopuna je tiha, osim kad donosi ⚠.

Što je prva poruka rekla pamti se pri slanju (`snapshot`, tablica `podaci`); poslane dopune
se pribrajaju (`merge`), pa ista novost ne stiže dvaput. Za poruke poslane prije ove dopune
snimke nema: tada se zna samo lokacija portala koji je nikad nema (oglasnik, burza,
realestatecroatia) ili je uvijek ima točnu (vender)."""

import html
import json
import re

from .ispu import APPROX_RADIUS_M, parcels_in_text
from .models import HOUSE, LAND, Decision, Listing
from . import risks
from .text import fmt_m2

NO_COORDS = {"oglasnik", "realestatecroatia", "burza"}   # portal nema lokaciju na karti
ALWAYS_PRECISE = {"vender"}                               # portal uvijek ima točnu oznaku
# Upozorenja o podacima portala, ne o nekretnini (drugi portal ih ima ili nema): nisu novost.
_NOISE = ("cijena", "površina", "vrsta zemljišta nije navedena", "parking nije naveden", "lokacija nesigurna",
          "oglas je istekao")
# Razlozi odbijanja koji ne dolaze od novog podatka: granice cijene i površine (blizanac je ±1 %)
# i grad/općina izvan popisa (blizanac je u istom gradu/općini – to je promjena pravila).
OLD_NEWS = ("cijena ", "cijena na upit", "površina ", "lokacija nije na popisu")


def new_reasons(d: Decision) -> list[str]:
    """Razlozi odbijanja koje donosi novi portal (vrsta, naselje, rečenica iz opisa…)."""
    return [r for r in d.reasons if not r.startswith(OLD_NEWS)]


def potential_rank(x: Listing) -> int:
    """Koliko dobru lokaciju oglas daje (prije provjere na ISPU-u)."""
    if parcels_in_text(f"{x.title}. {x.description}"):
        return 3
    lat, lon = x.extra.get("lat"), x.extra.get("lon")
    if lat and lon and not x.extra.get("priblizna_lokacija", True):
        return 2
    radius = x.extra.get("krug_m") or APPROX_RADIUS_M.get(x.source, APPROX_RADIUS_M["default"])
    return 1 if lat and lon and radius and x.kind == LAND else 0


def checked_rank(x: Listing) -> int:
    """Na čemu se temelji redak 🗺 u poruci (0: nije provjereno)."""
    if "lokacija_rang" in x.extra:
        return int(x.extra["lokacija_rang"] or 0)
    gp = x.extra.get("gp") or ""                 # neposlana obavijest iz ranije verzije
    if not gp or "nije provjereno" in gp:
        return 0
    return 3 if "k.č." in gp else 2 if "oznaci na karti" in gp else 1 if gp.startswith("🗺 Krug") else 0


def unchecked(x: Listing) -> bool:
    """ISPU nije stigao provjeriti (vrijeme pokretanja, ISPU ne odgovara): dopuna čeka."""
    gp = x.extra.get("gp") or ""
    return "nije provjereno (vremensko" in gp or "nije provjereno (ISPU" in gp


def warning_key(w: str) -> str:
    """Isto upozorenje ili razlog s drugog portala može citirati drugu rečenicu ili drugi izvor
    ("nije građevinsko (Poljoprivredno zemljište)" / "(naslov)", "ruševina: „…”"): uspoređuje se
    oznaka – bez citata i bez zagrade na kraju."""
    for rule in risks.RULES:
        if w.startswith(f"{rule.label}:"):
            return rule.label
    if w.startswith("parking: „"):
        return "parking: citat"
    w = re.sub(r":\s*„.*$", "", w)
    return re.sub(r"\s*\([^()]*\)$", "", w).strip() or w


def place_line(x: Listing, d: Decision) -> str:
    mjere = x.extra.get("mjere") or {}
    settlement = x.settlement or (mjere.get("naselje") if mjere.get("tocno") else "") or ""
    jls = d.jls or x.municipality
    if settlement and settlement != jls:
        return f"{jls} – {settlement}" if jls else settlement
    return ""


def _parking(x: Listing) -> str:
    """Samo kad portal kaže da parking postoji (polje ili opis): "nema podataka", "nije naveden" i
    okućnica umjesto parkinga nisu novost."""
    line = x.extra.get("parking_redak") or ""
    low = line.lower()
    return line if line.startswith("🚗") and not any(w in low for w in ("nije", "nema", "okućnica")) else ""


def snapshot(x: Listing, d: Decision) -> dict:
    """Što poruka o oglasu kaže (za usporedbu s kasnijim kopijama na drugim portalima)."""
    def one(key):
        value = x.extra.get(key) or ""
        return [value] if value and "nije provjereno" not in value else []
    return {
        "lokacija": checked_rank(x),
        "gp": one("gp"),
        "ppv": one("ppv"),
        "uvjeti": one("uvjeti"),
        "naselje": place_line(x, d),
        "vrsta": (x.subtype or "") if x.kind == HOUSE else "",
        "okucnica": x.plot_area or 0,
        "godina": str(x.extra.get("godina_izgradnje") or ""),
        "obnova": str(x.extra.get("godina_obnove") or ""),
        "vlasnicki": bool(x.extra.get("vlasnicki_list")),
        "za_obnovu": bool(x.extra.get("za_obnovu")),
        "parking": _parking(x),
        "parcelacija": x.extra.get("parcelacija") or "",
        "upozorenja": sorted({warning_key(w) for w in d.warnings}),
        "razlozi": sorted({warning_key(r) for r in new_reasons(d)}),   # ⚠ "ne odgovara" već javljen
    }


def legacy(row: dict) -> dict:
    """Poruka poslana prije pamćenja snimke: zna se samo lokacija nekih portala."""
    if row.get("source") in NO_COORDS:
        return {"lokacija": 0, "gp": [], "ppv": []}       # 📏 je mogao biti i tada (naselje iz naslova)
    if row.get("source") in ALWAYS_PRECISE:
        return {"lokacija": 2}
    return {}


def load(row: dict) -> dict | None:
    try:
        value = json.loads(row.get("podaci") or "null")
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def merge(*infos: dict | None) -> dict:
    """Sve što su prva poruka i poslane dopune rekle. Ključ koji nijedna ne zna ostaje
    nepoznat (ne uspoređuje se)."""
    out: dict = {}
    for info in infos:
        for key, value in (info or {}).items():
            if key == "lokacija":
                out[key] = max(out.get(key, 0), int(value or 0))
            elif isinstance(value, list):
                out[key] = sorted(set(out.get(key, [])) | set(value))
            elif not out.get(key):
                out[key] = value
    return out


def _missing(old: dict, new: dict, key: str) -> bool:
    """Prva poruka podatak nije imala (a zna se da nije), novi portal ga ima."""
    return key in old and not old[key] and bool(new.get(key))


def news(old: dict, new: dict, x: Listing, d: Decision, rejected: bool = False,
         location_warnings: list[str] | None = None) -> list[str]:
    """Retci dopune (bez HTML-a): samo ono što prva poruka (i ranije dopune) nisu rekle."""
    lines = []
    if rejected:
        known = {warning_key(k) for k in old.get("razlozi") or []}
        lines += [f"⚠ prema ovom oglasu ne odgovara kriterijima: {r}" for r in new_reasons(d)
                  if warning_key(r) not in known]
    if _missing(old, new, "naselje"):
        lines.append(f"📍 {new['naselje']}")
    better = old.get("lokacija") is not None and new["lokacija"] > old["lokacija"]
    for key in ("gp", "ppv", "uvjeti"):
        # Bolja lokacija, ili prva poruka retka nije imala (npr. 📏 kad novi portal navodi naselje).
        # 📏 se ne uspoređuje kad se ne zna što je poruka rekla (stara poruka).
        if (better and (key != "uvjeti" or key in old)) or (key in old and not old[key]):
            lines += [v for v in new[key] if v not in old.get(key, [])
                      and (key != "ppv" or "na lokaciji" in v)]   # PPV naselja nije novost
    facts = []
    if _missing(old, new, "vrsta"):
        facts.append(f"vrsta: {new['vrsta']}")
    if _missing(old, new, "okucnica"):
        facts.append(f"okućnica {fmt_m2(new['okucnica'])}")
    if _missing(old, new, "godina"):
        facts.append(f"izgrađena {new['godina']}")
    if _missing(old, new, "obnova"):
        facts.append(f"obnovljena {new['obnova']}")
    if _missing(old, new, "vlasnicki"):
        facts.append("vlasnički list ✔")
    if facts:
        lines.append("🏗 " + " · ".join(facts))
    if _missing(old, new, "za_obnovu") and not rejected:    # odbijena ruševina nije "za obnovu"
        lines.append("🔨 za obnovu / starina (prema opisu)")
    if _missing(old, new, "parking"):
        lines.append(new["parking"])
    if _missing(old, new, "parcelacija"):
        lines.append(f"✂️ {new['parcelacija']}")
    noise = {d.location_evidence, x.extra.get("location_note")}
    if "upozorenja" in old:
        known = {warning_key(k) for k in old["upozorenja"]}
        warnings = [w for w in d.warnings if warning_key(w) not in known]
    else:                                          # stara poruka: samo upozorenja s bolje lokacije
        warnings = list(location_warnings or []) if better else []
    for w in warnings:
        if w and w not in noise and not w.startswith(_NOISE) and "prihvaća se samo" not in w \
                and not w.endswith("stiže jer spominje parcelaciju"):
            lines.append(f"⚠ {w if len(w) <= 200 else w[:197] + '…'}")
    return list(dict.fromkeys(lines))


def message(x: Listing, label: str, lines: list[str], original: dict | None = None) -> str:
    """Telegram HTML. original: prvi oglas kad dopuna nije odgovor na poruku (nema broja poruke)."""
    e = html.escape
    head = f"➕ <b>Dopuna s {e(label)}</b>"
    if original:
        head += f" za oglas:\n<i>{e((original.get('title') or '')[:150])}</i>"
    text = "\n".join([head, *(e(line) for line in lines)])
    return text if len(text) <= 4000 else text[:3999] + "…"
