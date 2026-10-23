"""Popis polja sa stranica oglasa (revizija 23. 10.: što portal daje, a ne čitamo).

Izvor ga puni pri čitanju stranice oglasa: nazivi polja i do PRIMJERA kratkih primjera
vrijednosti (bez opisa; kontakti se brišu). Runner ga na kraju pokretanja spaja u meta
"popis_polja:IZVOR:VRSTA" – tako Redmi javlja polja Njuškala, do kojeg GitHub ne dolazi
(alat tools/provjeri_lokaciju.py "polja:" za ostale portale). Puni se dok nema MAX_PAGES
stranica po vrsti, pa ne raste."""

import json

from .text import strip_contacts

MAX_PAGES = 80
PRIMJERA = 8
_seen: dict[str, dict] = {}


def record(source: str, kind: str, fields: dict[str, str]) -> None:
    entry = _seen.setdefault(f"{source}:{kind}", {"stranica": 0, "polja": {}})
    entry["stranica"] += 1
    for name, value in fields.items():
        field = entry["polja"].setdefault(str(name)[:60], {"n": 0, "primjeri": []})
        field["n"] += 1
        shown = strip_contacts(str(value or ""))[:40]
        if shown and shown not in field["primjeri"] and len(field["primjeri"]) < PRIMJERA:
            field["primjeri"].append(shown)


def save(state) -> None:
    """Spaja ovo pokretanje u bazu (meta) i prazni popis."""
    for key, new in list(_seen.items()):
        meta = f"popis_polja:{key}"
        try:
            old = json.loads(state.meta_get(meta) or "{}")
        except ValueError:
            old = {}
        if old.get("stranica", 0) >= MAX_PAGES:
            continue
        fields = old.get("polja") or {}
        for name, value in new["polja"].items():
            field = fields.setdefault(name, {"n": 0, "primjeri": []})
            field["n"] += value["n"]
            field["primjeri"] = (field["primjeri"] + [v for v in value["primjeri"] if v not in field["primjeri"]])[:PRIMJERA]
        state.meta_set(meta, json.dumps({"stranica": old.get("stranica", 0) + new["stranica"], "polja": fields},
                                        ensure_ascii=False))
    _seen.clear()
