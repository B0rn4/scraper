"""Prepoznavanje lokacije: grad/općina, naselja, katastarske općine i padeži.

Podaci:
- data/locations.yaml: gradovi i općine PGŽ s naseljima (generirano iz popisa
  lokacija index.hr, tools/build_locations.py) i oznakom "ukljuceno".
- data/locations_extra.yaml: ručno održavani dodaci (katastarske općine,
  kvartovi, nazivi koji su ujedno obične riječi, poznati lažni pogoci).
"""

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
        key = fold(name)
        key = self.aliases.get(key, key)
        return list(self._settlement_index.get(key, []))

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
        terms = [(name, re.compile(name_pattern(name)), owners) for name, owners in by_name.items()]
        # Duži nazivi prvi: "Mošćenička Draga" prije "Draga".
        terms.sort(key=lambda t: len(t[0]), reverse=True)
        return terms

    def scan_text(self, text: str) -> list[tuple[Jls, str]]:
        """Svi spomenuti gradovi/općine u tekstu, kao (jls, pronađeni oblik).

        Nazivi koji su i obične riječi (Kraj, Polje, Vrh…) broje se samo ako
        su napisani velikim početnim slovom. Naziv koji postoji u više
        gradova/općina vraća sve njih."""
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
                found.extend((jls, cased[m.start():m.end()]) for jls in owners)
        return found

    # --- odluka ----------------------------------------------------------

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

