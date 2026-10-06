"""Prepoznavanje lokacije: grad/općina, naselja, katastarske općine i padeži.

Podaci:
- data/locations.yaml: gradovi i općine PGŽ s naseljima (generirano iz popisa
  lokacija index.hr, tools/build_locations.py) i oznakom "ukljuceno".
- data/locations_extra.yaml: ručno održavani dodaci (katastarske općine,
  kvartovi, nazivi koji su ujedno obične riječi, poznati lažni pogoci).
"""

import csv
import re
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import yaml

from .text import fold, fold_case

DATA = Path(__file__).resolve().parent.parent / "data"

# Padežni nastavci. Jednorječni nazivi dobivaju nastavke prema završnom slovu
# (da "u Mošćenici" – selo kod Petrinje – ne bude isto što i "u Mošćenicama").
# Riječi višerječnih naziva (pridjev + imenica) dobivaju širi skup.
_ENDINGS_BY_LAST = {
    "a": "a|e|i|u|o|om|oj|ama",          # Rijeka, Baška (ženski rod)
    "e": "e|a|u|em|ama|ima",             # Mošćenice (množina), Selce (srednji rod)
    "i": "i|a|e|ima",                    # Ičići, Bogovići (muška množina)
    "o": "o|a|u|om|em",                  # Volosko (srednji rod)
}
_ENDINGS_CONSONANT = "a|u|om|em|e|i"     # Krk, Punat, Omišalj (muški rod)
_ENDINGS_WIDE = "a|e|i|u|o|om|oj|em|ama|ima|og|oga|ome|omu|im|ih"
_SIBILARIZATION = {"k": "c", "g": "z", "h": "s"}
_VOWELS = set("aeiou")
_FLEETING_A = re.compile(r"^(.*[^aeiou])a([^aeiou]{1,2})$")


def _word_pattern(word: str, wide: bool = False) -> str:
    """Regex za jednu (već normaliziranu) riječ naziva, sa svim padežima."""
    if len(word) <= 2 or not word.isalpha():
        return re.escape(word)
    last = word[-1]
    if last in _VOWELS:
        if last == "u":
            return re.escape(word)
        stems = {word[:-1]}
        if word[-2] in _SIBILARIZATION:
            stems.add(word[:-2] + _SIBILARIZATION[word[-2]])  # Rijeka → Rijeci
        endings = _ENDINGS_WIDE if wide else _ENDINGS_BY_LAST[last]
        optional = ""
    else:
        stems = {word}
        m = _FLEETING_A.match(word)
        if m:  # nepostojano a: Punat → Puntu, Omišalj → Omišlju, Bakar → Bakru
            stems.add(m.group(1) + m.group(2))
        endings = _ENDINGS_WIDE if wide else _ENDINGS_CONSONANT
        optional = "?"
    stem_rx = "|".join(sorted(map(re.escape, stems), key=len, reverse=True))
    return f"(?:{stem_rx})(?:{endings}){optional}"


def name_pattern(name: str) -> str:
    """Regex za cijeli (višerječni) naziv, nad normaliziranim tekstom."""
    words = fold(name).split()
    wide = len(words) > 1
    return r"\b" + r"\s+".join(_word_pattern(w, wide) for w in words) + r"\b"


@dataclass
class Jls:
    key: str
    name: str
    kind: str              # "grad" ili "općina"
    included: bool
    settlements: list[str] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)   # k.o., kvartovi, drugi nazivi


@dataclass
class LocationResult:
    jls: Jls | None
    included: bool | None   # None = nepoznato
    evidence: str = ""
    ambiguous: bool = False


PASS_, WARN_, REJECT_ = "prolazi", "upozorenje", "odbijen"
REASONS = ("daleko od mora", "daleko od Rijeke", "grad Rijeka")
_DECISIONS = {"prolaz": PASS_, "upozorenje": WARN_, "upozorenje da je rijeka": WARN_, "odbijen": REJECT_}


def _join_reasons(reasons: list[str]) -> str:
    if reasons == ["daleko od mora", "daleko od Rijeke"]:
        return "daleko od mora i od Rijeke"
    return ", ".join(reasons)


def _num(value) -> float | None:
    try:
        return float(str(value).replace(",", ".")) if str(value or "").strip() else None
    except ValueError:
        return None


def load_decisions(path: Path) -> dict[str, dict[str, dict]]:
    """Odluke po naseljima: {grad/općina: {naselje: {odluka, razlozi, razlog, naziv}}}.
    Odluke su "Prolaz", "Upozorenje", "Upozorenje da je Rijeka" i "Odbijen"; razlog
    upozorenja (i odbijanja) slijedi iz stupaca daleko_od_mora i daleko_od_rijeke."""
    out: dict[str, dict[str, dict]] = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            raw = (row.get("odluka") or "").strip().lower()
            decision = _DECISIONS.get(raw)
            if not decision:
                continue
            reasons = [r for r, col in (("daleko od mora", "daleko_od_mora"), ("daleko od Rijeke", "daleko_od_rijeke"))
                       if (row.get(col) or "").strip().lower() == "da"]
            if "rijeka" in raw:
                reasons = ["grad Rijeka"]
            out.setdefault(row["grad_opcina"], {})[fold(row["naselje"])] = {
                "odluka": decision, "razlozi": reasons, "razlog": _join_reasons(reasons), "naziv": row["naselje"],
                "more_km": _num(row.get("more_zracno_km")), "rijeka_min": _num(row.get("rijeka_min")),
                "zagreb_min": _num(row.get("zagreb_min"))}
    return out


class Locator:
    def __init__(self, data_dir: Path = DATA):
        base = yaml.safe_load((data_dir / "locations.yaml").read_text(encoding="utf-8"))
        extra = yaml.safe_load((data_dir / "locations_extra.yaml").read_text(encoding="utf-8"))
        self.county = base["zupanija"]
        included = {fold(n) for n in extra.get("ukljuceno", [])}
        self.jls: dict[str, Jls] = {}
        for item in base["jls"]:
            jls = Jls(
                key=fold(item["naziv"]),
                name=item["naziv"],
                kind=item.get("vrsta", ""),
                included=fold(item["naziv"]) in included,
                settlements=list(item.get("naselja") or []),
            )
            self.jls[jls.key] = jls
        missing = included - set(self.jls)
        if missing:
            raise ValueError(f"U locations.yaml nedostaju uključene jedinice: {sorted(missing)}")
        for name, extras in (extra.get("dodatno") or {}).items():
            self.jls[fold(name)].extra.extend(extras)
        self.aliases = {fold(a): fold(t) for a, t in (extra.get("sinonimi") or {}).items()}
        self.cadastral = {fold(k): self.jls[fold(v)] for k, v in (extra.get("katastarske_opcine") or {}).items()}
        self.common_words = {fold(w) for w in extra.get("obicne_rijeci", [])}
        self.settlement_aliases = {fold(a): fold(t) for a, t in (extra.get("drugi_nazivi_naselja") or {}).items()}
        self.only_settlements = {self.jls[fold(k)].name: {fold(n) for n in v}
                                 for k, v in (extra.get("samo_naselja") or {}).items()}
        self.decisions = load_decisions(data_dir / "naselja_udaljenosti.csv")
        # Naselja čiji je naziv u popisu odluka samo jednom: odluka vrijedi i kad ih portal
        # vodi pod drugim gradom/općinom (index.hr npr. Oprič i Dobreć vodi pod Opatijom).
        counts: dict[str, int] = {}
        for rows in self.decisions.values():
            for key in rows:
                counts[key] = counts.get(key, 0) + 1
        self.unique_decisions = {key: row for rows in self.decisions.values() for key, row in rows.items()
                                 if counts[key] == 1}
        self.false_phrases = [re.compile(r"\b" + re.escape(fold(p)) + r"\b") for p in extra.get("lazni_pogoci", [])]

    # --- pretraživanje po strukturiranim poljima -------------------------

    def by_name(self, name: str) -> Jls | None:
        key = fold(name)
        key = re.sub(r"^(grad|opcina)\s+", "", key)
        key = self.aliases.get(key, key)
        return self.jls.get(key)

    @cached_property
    def _settlement_index(self) -> dict[str, list[Jls]]:
        index: dict[str, list[Jls]] = {}
        for jls in self.jls.values():
            for name in [jls.name, *jls.settlements, *jls.extra]:
                index.setdefault(fold(name), [])
                if jls not in index[fold(name)]:
                    index[fold(name)].append(jls)
        return index

    def by_settlement(self, name: str) -> list[Jls]:
        key = self.canonical(name)
        return list(self._settlement_index.get(key, []))

    def knows(self, place: str) -> bool:
        """Je li naziv mjesta (naselje, grad/općina, kvart; bez kućnog broja) u županiji."""
        place = re.sub(r"\s+\d+\w*\s*$", "", place or "").strip()
        return bool(place) and self.resolve(settlement=place, text=place).jls is not None

    def canonical(self, name: str) -> str:
        """Normalizirani naziv naselja: drugi nazivi (Poljice → poljica) i sinonimi."""
        key = fold(name)
        key = self.settlement_aliases.get(key, key)
        return self.aliases.get(key, key)

    # --- pretraživanje slobodnog teksta ----------------------------------

    @cached_property
    def _terms(self) -> list[tuple[str, re.Pattern, list[Jls]]]:
        """(normalizirani naziv, regex, gradovi/općine s tim nazivom), duži nazivi prvi."""
        by_name: dict[str, list[Jls]] = {}
        for jls in self.jls.values():
            for name in [jls.name, *jls.settlements, *jls.extra]:
                owners = by_name.setdefault(fold(name), [])
                if jls not in owners:
                    owners.append(jls)
        for alias, target in self.aliases.items():
            if target in self.jls:
                owners = by_name.setdefault(alias, [])
                if self.jls[target] not in owners:
                    owners.append(self.jls[target])
        for alias, target in self.settlement_aliases.items():
            by_name.setdefault(alias, list(by_name.get(target, [])))
        terms = [(name, re.compile(name_pattern(name)), owners) for name, owners in by_name.items()]
        # Duži nazivi prvi: "Mošćenička Draga" prije "Draga".
        terms.sort(key=lambda t: len(t[0]), reverse=True)
        return terms

    def scan_text(self, text: str) -> list[tuple[Jls, str]]:
        """Svi spomenuti gradovi/općine u tekstu, kao (jls, pronađeni oblik).

        Nazivi koji su i obične riječi (Kraj, Polje, Vrh…) broje se samo ako
        su napisani velikim početnim slovom. Naziv koji postoji u više
        gradova/općina vraća sve njih."""
        return [(jls, found) for jls, _, found in self._scan(text)]

    def scan_names(self, text: str) -> list[tuple[Jls, str]]:
        """Kao scan_text, ali s osnovnim (normaliziranim) nazivom: "u Njivicama" → "njivice"."""
        return [(jls, self.settlement_aliases.get(name, name)) for jls, name, _ in self._scan(text)]

    def _scan(self, text: str) -> list[tuple[Jls, str, str]]:
        cased = fold_case(text)
        folded = cased.lower()
        mask = [False] * len(folded)
        for phrase in self.false_phrases:
            for m in phrase.finditer(folded):
                mask[m.start():m.end()] = [True] * (m.end() - m.start())
        found = []
        for name, regex, owners in self._terms:
            common = name in self.common_words
            for m in regex.finditer(folded):
                if any(mask[m.start():m.end()]):
                    continue
                if common and not cased[m.start()].isupper():
                    continue
                mask[m.start():m.end()] = [True] * (m.end() - m.start())
                found.extend((jls, name, cased[m.start():m.end()]) for jls in owners)
        return found

    def settlement_verdict(self, jls_name: str, settlement: str, text: str) -> tuple[str, str] | None:
        """Odluka iz popisa naselja (data/naselja_udaljenosti.csv): (REJECT ili WARN, tekst)
        ili None (prolazi bez napomene).

        Naselje: polje naselja s portala, inače naselja spomenuta u lokaciji/naslovu.
        Naziv koji je ujedno grad/općina ("Krk", "Rijeka") nije određeno naselje. Bez
        određenog naselja oglas prolazi; napomenu dobije samo ako je imaju sva
        prihvaćena naselja tog grada/općine (npr. Rijeka, Krk – daleko od Rijeke)."""
        table = self.decisions.get(jls_name, {})
        only = self.only_settlements.get(jls_name)
        specific, field, elsewhere = self._places(jls_name, settlement, text)
        if only is not None:
            outside = [n for n in specific if n not in only]
            if outside and len(outside) == len(specific):
                names = ", ".join(self._display(jls_name, n) for n in outside)
                return REJECT_, f"{names} ({jls_name}): prihvaća se samo {', '.join(sorted(self._display(jls_name, n) for n in only))}"
            if not specific and field not in only:
                return WARN_, f"{jls_name}: prihvaća se samo mjesto {', '.join(sorted(self._display(jls_name, n) for n in only))} – provjeri"
        rows = [(n, table.get(n) or elsewhere[n]) for n in specific if n in table or n in elsewhere]
        if not rows and field in table:
            rows = [(field, table[field])]          # npr. naselje "Krk" (grad Krk)
        if not rows:
            return self._town_verdict(jls_name, table)
        rejected = [(n, r) for n, r in rows if r["odluka"] == REJECT_]
        kept = [(n, r) for n, r in rows if r["odluka"] != REJECT_]
        if rejected and not kept:
            n, r = rejected[0]
            why = f" ({r['razlog']})" if r["razlog"] else ""
            return REJECT_, f"{r['naziv']}: isključeno po popisu naselja{why}"
        by_reason: dict[str, list[str]] = {}
        for _, r in kept:
            if r["odluka"] == WARN_ and r["razlog"]:
                by_reason.setdefault(r["razlog"], []).append(r["naziv"])
        notes = [f"{', '.join(names)}: {reason}" for reason, names in by_reason.items()]
        if rejected:
            notes.append("oglas spominje i " + ", ".join(r["naziv"] for _, r in rejected) + " (isključeno po popisu)")
        return (WARN_, "; ".join(notes)) if notes else None

    def _places(self, jls_name: str, settlement: str, text: str) -> tuple[list[str], str, dict]:
        """Određena naselja oglasa (normalizirani nazivi), polje naselja i odluke za naselja
        drugih gradova/općina čiji je naziv jedinstven."""
        own = {fold(n) for n in self.jls[fold(jls_name)].settlements + self.jls[fold(jls_name)].extra} \
            if fold(jls_name) in self.jls else set()
        field = fold(settlement) if settlement else ""
        field = self.settlement_aliases.get(field, field)
        elsewhere = {n: r for n, r in self.unique_decisions.items()
                     if n not in own and n not in self.common_words}   # ne "Centar", "Draga"…
        specific = [field] if field and (field in own or field in elsewhere) and self.by_name(field) is None else []
        if not specific:
            specific = sorted({name for j, name in self.scan_names(text)
                               if (j.name == jls_name or name in elsewhere)
                               and self.by_name(name) is None and name != "centar"})
        return specific, field, elsewhere

    def settlement_row(self, jls_name: str, settlement: str, text: str) -> tuple[dict, bool] | None:
        """Red popisa naselja za oglas (udaljenosti) i je li naselje određeno (False:
        oglas navodi samo grad/općinu, pa se uzima istoimeno naselje, npr. grad Krk)."""
        table = self.decisions.get(jls_name, {})
        specific, field, elsewhere = self._places(jls_name, settlement, text)
        rows = [table.get(n) or elsewhere[n] for n in specific if n in table or n in elsewhere]
        if len(rows) == 1:
            return rows[0], True
        if not rows and field in table:
            return table[field], True
        if not rows and fold(jls_name) in table:
            return table[fold(jls_name)], False
        return None

    def _town_verdict(self, jls_name: str, table: dict) -> tuple[str, str] | None:
        accepted = [r for r in table.values() if r["odluka"] != REJECT_]
        if not accepted or any(r["odluka"] == PASS_ for r in accepted):
            return None
        common = set.intersection(*(set(r["razlozi"]) for r in accepted))
        if not common:
            return None
        reasons = [x for x in REASONS if x in common]
        if reasons == ["grad Rijeka"]:
            return WARN_, "grad Rijeka"
        return WARN_, f"{jls_name}: {_join_reasons(reasons)}"

    def _display(self, jls_name: str, key: str) -> str:
        row = self.decisions.get(jls_name, {}).get(key)
        if row:
            return row["naziv"]
        jls = self.jls.get(fold(jls_name))
        return next((n for n in (jls.settlements if jls else []) if fold(n) == key), key.title())

    def resolve(self, municipality: str = "", settlement: str = "", county: str = "", text: str = "") -> LocationResult:
        if county and fold(county) not in (fold(self.county), fold(self.county) + " zupanija"):
            return LocationResult(None, False, f"županija: {county}")
        if municipality:
            jls = self.by_name(municipality)
            if jls:
                return LocationResult(jls, jls.included, f"grad/općina: {municipality}")
        if settlement:
            matches = self.by_settlement(settlement)
            if len(matches) == 1:
                return LocationResult(matches[0], matches[0].included, f"naselje: {settlement}")
            if len(matches) > 1:
                states = {j.included for j in matches}
                if states == {True}:
                    return LocationResult(matches[0], True, f"naselje: {settlement}", ambiguous=True)
                if states == {False}:
                    return LocationResult(matches[0], False, f"naselje: {settlement}")
                names = ", ".join(j.name for j in matches)
                return LocationResult(None, None, f"naselje {settlement} postoji u više mjesta: {names}", ambiguous=True)
        if text:
            found = self.scan_text(text)
            inc = [(j, f) for j, f in found if j.included]
            exc = [(j, f) for j, f in found if not j.included]
            if inc and not exc:
                return LocationResult(inc[0][0], True, f"tekst: „{inc[0][1]}”")
            if inc and exc:
                return LocationResult(
                    inc[0][0], True,
                    f"tekst: „{inc[0][1]}”, ali spominje i „{exc[0][1]}” ({exc[0][0].name})",
                    ambiguous=True,
                )
            if exc:
                return LocationResult(exc[0][0], False, f"tekst: „{exc[0][1]}”")
        shown = municipality or settlement
        return LocationResult(None, None, f"nepoznata lokacija: {shown}" if shown else "nepoznata lokacija")

