"""Već viđeni oglasi: isti oglas na drugom portalu ili ponovno objavljen pod novim brojem.

Oglas je "isti" kao već viđeni (poslan, u početnom popisu ili tiho zabilježen) ako su
vrsta i grad/općina isti, površina se razlikuje najviše 2 % (barem 1 m²), naselja
spomenuta u naslovu se ne razlikuju (Vrh ≠ Krk-Centar), a uz to:
- cijena je ista do eura i površina do pola kvadrata – a kod okruglih brojeva
  (npr. 299.000 € i 100 m²) i zajedničko naselje ili riječi iz naslova, ili
- cijena se razlikuje najviše 1 % i oglasi dijele naselje ili riječi iz naslova, ili
- oba su "cijena na upit" (1 ili 100 €), a dijele naselje ili riječi iz naslova.
Ako je novi oglas jeftiniji od svih istih viđenih (više od 1 %), ipak stiže, s
napomenom. Pravilo je namjerno oprezno: kad nije sigurno, oglas stiže (dobru ponudu
je gore propustiti nego dobiti dvaput)."""

import gzip
import json
from pathlib import Path

from .models import Decision, Listing
from .text import fold

PRICE_TOLERANCE = 0.01
CHEAPER_RANGE = 0.30   # do koliko skuplji raniji oglas još može biti "isti, sad jeftiniji"
# Riječi koje ništa ne govore o tome je li to ista nekretnina.
_GENERIC = set("""kuca kuce kucu prodaja prodaje prodajem obiteljska obiteljsku samostojeca samostojecu zemljiste
zemljista gradevinsko gradevinska otok otoku pogled pogledom more mora moru okucnica okucnicom nova novo
novogradnja vila vile vilu centar centru blizini blizina mirnoj lokaciji lokacija prilika odlicna odlican
atraktivna atraktivno prekrasna prekrasan lijepa sobe soba garazom garaza bazen bazenom parcela teren""".split())
FIELDS = ("key", "source", "kind", "jls", "price", "area", "title", "settlement", "notified_at", "notified_price")
_PLACE_WORDS: set[str] = set()   # riječi iz naziva naselja i gradova/općina (nisu opis nekretnine)


def _words(title: str) -> set[str]:
    """Opisne riječi naslova: bez općenitih riječi i bez naziva mjesta (inače bi sve kuće u
    Baški imale zajedničku riječ "baska")."""
    return {w for w in fold(title or "").split()
            if len(w) >= 4 and not w.isdigit() and w not in _GENERIC and w not in _PLACE_WORDS}


def _learn_places(locator) -> None:
    if not _PLACE_WORDS and locator is not None:
        for jls in locator.jls.values():
            for name in (jls.name, *jls.settlements):
                _PLACE_WORDS.update(fold(name).split())


def places(r: dict, locator=None) -> set[str]:
    """Naselja (ne sam grad/općina) iz naslova i polja naselja; "Centar" se ne broji."""
    if "_places" in r:
        return r["_places"]
    _learn_places(locator)
    found = set()
    if locator is not None:
        # Osnovni oblik naselja ("u Barušićima" = "Barušići"), bez naziva grada/općine.
        for jls, name, written in locator._scan(f"{r.get('title') or ''}, {r.get('settlement') or ''}"):
            if jls.name == r.get("jls") and locator.by_name(written) is None and locator.by_name(name) is None:
                found.add(name)
    elif r.get("settlement"):
        found.add(fold(r["settlement"]))
    found.discard("centar")
    if locator is not None:
        r["_places"] = found
    return found


def _same_place(a: dict, b: dict) -> bool:
    if places(a) & places(b):
        return True
    wa, wb = _words(a.get("title")), _words(b.get("title"))
    return bool(wa and wb) and len(wa & wb) / len(wa | wb) >= 0.3


def _round(price: float, area: float) -> bool:
    """Okrugla površina (100 m²) i cijena na tisuću – takvih je mnogo, pa treba dokaz."""
    return price % 1_000 == 0 and area == int(area) and area % 10 == 0


def same_property(new: dict, old: dict, cheaper_ok: bool = False) -> bool:
    """Isti oglas? cheaper_ok: dopušta da je raniji oglas skuplji (za "sad jeftiniji").
    Na istom portalu samo ponovna objava: ista cijena i površina (više jedinica istog
    projekta ima bliske, ali različite cijene – to su različite nekretnine)."""
    if new["kind"] != old["kind"] or not new.get("jls") or new["jls"] != old.get("jls"):
        return False
    pn, po, an, ao = new.get("price"), old.get("price"), new.get("area"), old.get("area")
    if not (an and ao) or abs(an - ao) > max(1.0, 0.02 * ao):
        return False
    pa, pb = places(new), places(old)
    if pa and pb and not pa & pb:
        return False  # naslovi spominju različita naselja
    asked_n, asked_o = not pn or pn <= 100, not po or po <= 100      # "cijena na upit" (1, 100 €)
    if asked_n or asked_o:
        # Oba na upit: dovoljni površina i isto mjesto ili naslov (agencija ga stavlja na više portala).
        return asked_n and asked_o and _same_place(new, old)
    if abs(pn - po) <= 1 and abs(an - ao) <= 0.5 and (not _round(pn, an) or _same_place(new, old)):
        return True
    if new.get("source") and new.get("source") == old.get("source"):
        return False
    close = abs(pn - po) <= PRICE_TOLERANCE * po
    pricier = cheaper_ok and po > pn and po <= pn * (1 + CHEAPER_RANGE)
    return (close or pricier) and _same_place(new, old)


def row(listing: Listing, decision: Decision) -> dict:
    return {"key": listing.key, "source": listing.source, "kind": listing.kind, "jls": decision.jls,
            "price": listing.price, "area": listing.area, "title": listing.title,
            "settlement": listing.settlement, "notified_at": None, "notified_price": None}


class Seen:
    """Već viđeni oglasi iz jedne ili više baza (GitHub, Redmi) i iz ovog pokretanja."""

    def __init__(self, locator=None):
        self.locator = locator
        self.rows: dict[tuple, list[dict]] = {}

    def add(self, r: dict) -> None:
        if r.get("jls") and r.get("price") and r.get("area"):
            places(r, self.locator)
            self.rows.setdefault((r["kind"], r["jls"]), []).append(r)

    def add_state(self, state) -> None:
        for r in state.seen_rows():
            self.add(r)

    def add_file(self, path: Path) -> None:
        if path and Path(path).exists():
            for values in json.loads(gzip.decompress(Path(path).read_bytes())):
                self.add(dict(zip(FIELDS, values)))

    def twins(self, new: dict, cheaper_ok: bool = True) -> list[dict]:
        places(new, self.locator)
        return [r for r in self.rows.get((new["kind"], new.get("jls")), [])
                if r["key"] != new["key"] and same_property(new, r, cheaper_ok)]


def export(state, path: Path) -> int:
    """Sažetak viđenih oglasa za drugi uređaj (GitHub → Redmi)."""
    rows = [[r[f] for f in FIELDS] for r in state.seen_rows()]
    Path(path).write_bytes(gzip.compress(json.dumps(rows, ensure_ascii=False).encode("utf-8")))
    return len(rows)
