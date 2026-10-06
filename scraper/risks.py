"""Opasni izrazi u oglasu: pravni i drugi problemi koji se ne vide iz cijene i površine.

Oglas se odbija samo kad je problem nedvosmislen (prodaje se suvlasnički/idealni dio).
Sve ostalo je upozorenje (⚠) s citiranom rečenicom, da odluku doneseš sam – dobru
ponudu je gore izgubiti nego pročitati jednu rečenicu više. Svaki izraz ima i
niječne oblike koji ga poništavaju u istoj rečenici ("bez tereta", "legalizirano",
"vlasništvo 1/1")."""

import re
from dataclasses import dataclass

from .text import fold


@dataclass(frozen=True)
class Rule:
    label: str
    pattern: re.Pattern
    ok: re.Pattern | None = None     # niječni/umirujući izraz u istoj rečenici poništava pogodak
    reject: bool = False
    skip_sources: tuple = ()


def _re(text: str) -> re.Pattern:
    """Izrazi su nad fold() tekstom: mala slova, bez dijakritika, "/" i crtice su razmaci (1/2 → "1 2")."""
    return re.compile(text)


# Suvlasnički ili idealni dio. "Idealni" je i obična pridjevska riječ ("kuća u idealnom
# dijelu Malinske"), pa se kao dio vlasništva broji samo kad iza slijedi nekretnina ili
# razlomak ("idealni dio od 1/2 kuće", "idealni dio nekretnine").
_SHARE = (r"(suvlasnick\w* (dio|dijel\w*|udio|udjel\w*)"
          r"|(?<!\bu )(?<!\bna )idealn\w* (dio|dijel\w*|udio|udjel\w*)"
          r"(?= (od )?(\d|nekretnin|kuc|zemljist|cestic|parcel|objekt|stan|zgrad)))")

RULES = [
    # --- odbija se: prodaje se samo dio nekretnine ---
    Rule("prodaje se suvlasnički dio",
         _re(rf"\b(prodaj\w*|nudi\w*|u ponudi)\b[^.]{{0,40}}\b{_SHARE}"
             rf"|\b{_SHARE}\b[^.]{{0,25}}\b(na prodaju|se prodaje|prodajem)"
             r"|\bprodaj\w*\b[^.]{0,15}\b(1 2|1 3|1 4|2 3|polovic\w*|polovin\w*) (kuce|nekretnine|zemljista|parcele)"),
         reject=True),
    # --- upozorenja ---
    Rule("suvlasništvo", _re(r"\bsuvlasni\w*|\bvise (su)?vlasnika"),
         ok=_re(r"\bbez suvlasni|\bnema suvlasni|\b1 1\b|\bjedan vlasnik|\bjedini vlasnik")),
    Rule("nasljednici / ostavina", _re(r"\bnasljedni\w*|\bostavin\w*|\bnasljedstv\w*"),
         ok=_re(r"\b(zavrsen\w*|proveden\w*|okoncan\w*|rijesen\w*|pravomocn\w*)")),
    Rule("papiri nisu sređeni",
         _re(r"\bbez papira|\bnesreden\w* (papir|vlasni|dokument|zemljisn)|\bpapiri (nisu|jos nisu|nisu jos) sreden"
             r"|\bvlasnistvo (nije|jos nije) (sredeno|rijeseno|upisano)|\bpapiri u postupku")),
    Rule("legalizacija / bez dozvole",
         _re(r"\bnije legaliz\w*|\bnelegaliz\w*|\bu postupku legalizacij\w*|\bzahtjev\w* za legalizacij\w*"
             r"|\bbespravn\w*|\bbez (gradevinsk\w* |uporabn\w* )?dozvol\w*|\bpredan\w* (zahtjev\w* )?za legalizacij\w*"),
         ok=_re(r"\bnije potrebn\w*")),
    Rule("nije upisano u zemljišne knjige",
         _re(r"\bvanknjizn\w*|\bnije uknjizen\w*|\bneuknjizen\w*|\bnije upisan\w* u (zemljisn|gruntovn)"
             r"|\bnije u gruntovnic\w*|\bnije provedeno u (zemljisn|gruntovn)")),
    Rule("pravo stanovanja / plodouživanje",
         _re(r"\bpravo (dozivotnog |dozivotno )?stanovanj\w*|\bdozivotn\w* (pravo|stanovanj\w*|uzdrzavanj\w*)"
             r"|\bplodouziv\w*|\bsluznost\w* stanovanj\w*"),
         ok=_re(r"\bbez (prava|plodouz)|\bnema (prava|plodouz)|\bbrisan\w*")),
    Rule("teret / hipoteka / ovrha",
         _re(r"\bhipotek\w*|\bovrh\w*|\bzabiljezb\w* spor\w*|\bupisan\w* teret\w*|\bpod teretom|\bopterecen\w* (hipotek|kredit|teret)"),
         ok=_re(r"\bbez (ikakvih )?teret\w*|\bnema (nikakvih )?teret\w*|\bnije opterecen\w*|\bcist\w* od teret\w*"
                r"|\bbez hipotek\w*|\bslobodn\w* od teret\w*"),
         skip_sources=("fina",)),
    Rule("kulturno dobro / zaštićena cjelina",
         _re(r"\bzasticen\w* (kulturn\w* dobr\w*|spomeni\w*|(star\w* |povijesn\w* |gradsk\w* )*jezgr\w*|cjelin\w*)"
             r"|\bspomeni\w* kulture|\bregist\w* kulturnih dobara|\bkulturn\w* dobr\w*|\bkonzervator\w*"
             r"|\bkulturno povijesn\w* (urbanistick\w* |ruraln\w* )?(cjelin\w*|jezgr\w*)"
             r"|\bpod zastitom (drzave|ministarstva|konzerv\w*)"),
         ok=_re(r"\bnije (zasticen\w*|pod zastitom|kulturno dobro)|\bnije u zasticen|\bizvan zasticen|\bbez konzervator")),
    Rule("izvan građevinskog područja",
         _re(r"\b(izvan|van) gradevinsk\w* (podruc\w*|zon\w*)"),
         ok=_re(r"\bdijelom\b|\bvecim dijelom\b|\bdio\b.{0,20}\bu gradevinsk")),
    Rule("nema kolnog pristupa",
         _re(r"\bpjesack\w* (pristup|stazom|putem)|\bbez (kolnog |kolnim )?(pristupa|prilaza)\b|\bnema (kolnog |kolni )?(pristup|prilaz)"
             r"|\bsamo pjesice\b|\bnema pristupa (autom|automobilom|vozilom)|\bnije moguc\w* pristup (autom|vozilom)"),
         ok=_re(r"\bkoln\w* pristup do\b")),
]

_SENTENCES = re.compile(r"(?<=[.!?…])\s+|\n+")


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCES.split(text or "") if s.strip()]


def scan(text: str, source: str = "") -> list[tuple[Rule, str]]:
    """Pronađena pravila i rečenica iz oglasa (izvorni tekst, do 160 znakova)."""
    found, seen = [], set()
    for sentence in sentences(text):
        folded = fold(sentence)
        for rule in RULES:
            if rule.label in seen or source in rule.skip_sources:
                continue
            if rule.pattern.search(folded) and not (rule.ok and rule.ok.search(folded)):
                seen.add(rule.label)
                found.append((rule, sentence if len(sentence) <= 160 else sentence[:157] + "…"))
    return found
