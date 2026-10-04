"""Analiza FINA-inog CSV izvoza Očevidnika: kako su zapisani sudovi i mjesta.

Sprema samo zbirne podatke (brojeve, nazive institucija, nazive mjesta i
katastarskih općina). Opisi predmeta se ne spremaju jer mogu sadržavati osobne
podatke, a repozitorij je javan.
"""

import csv
import io
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import requests

CSV_URL = "https://ponip.fina.hr/ocevidnik-web/preuzmi/csv"
OUT = Path(__file__).parent / "results" / "fina"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
    )
}

# Široki uzorci: osnova riječi + nepostojano a + glasovne promjene (k→c).
PLACES = {
    "Baška": r"\bBaš[kcć]\w*",
    "Dobrinj": r"\bDobrinj\w*",
    "Kostrena": r"\bKostren\w*",
    "Lovran": r"\bLovran\w*",
    "Malinska-Dubašnica": r"\bMalinsk\w*|\bDubašni\w*",
    "Mošćenička Draga": r"\bMošćeni\w*",
    "Omišalj": r"\bOmiš(?:a)?lj\w*",
    "Punat": r"\bPun(?:a)?t\w*",
    "Vrbnik": r"\bVrbni\w*",
    "Crikvenica": r"\bCrikveni\w*",
    "Kraljevica": r"\bKraljevic\w*",
    "Krk": r"\bKrk\w*",
    "Novi Vinodolski": r"\bNov\w*\s+Vinodolsk\w*",
    "Opatija": r"\bOpatij\w*",
    "Rijeka": r"\bRije[kcč]\w*",
    "Bakar (isključen)": r"\bBak(?:a)?r\w*",
}

INSTITUTION = re.compile(r"sud|porezn|ured|ministarstv|agencij|fina|uprava", re.I)
REGION_COURT = re.compile(r"Rije|Krk|Opatij|Crikven|Delnic|Rab\b|Lošinj|Cres", re.I)
KO = re.compile(
    r"(?:\b[kK]\.\s?[oO]\.|katastarsk\w*\s+općin\w*)\s*:?\s*"
    r"([A-ZČĆŽŠĐ][\w\-]+(?:\s+(?:[A-ZČĆŽŠĐ][\w\-]+|na|u|pri|kod))?(?:\s+[A-ZČĆŽŠĐ][\w\-]+)?)",
)
BUILDING_LAND = re.compile(r"građevinsk\w*\s+zemlji|građevinsk\w*\s+čestic|građevinsko", re.I)
AREA = re.compile(r"\d[\d.,]*\s*(?:m2|m²|čhv|čh|ha)\b", re.I)


def parse_date(value: str):
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    resp = requests.get(CSV_URL, headers=HEADERS, timeout=120)
    resp.raise_for_status()
    text = resp.content.decode("utf-8-sig", errors="replace")
    rows = list(csv.DictReader(io.StringIO(text), delimiter=";"))
    header = list(rows[0].keys()) if rows else []
    body_col = next((h for h in header if "Nadležno" in h), header[0])

    real_estate = [r for r in rows if r.get("Vrsta predmeta prodaje") == "nekretnina"]
    now = datetime.now()

    def is_active(r):
        end = parse_date(r.get("Datum i vrijeme završetka nadmetanja", "") or "")
        return end is None or end >= now

    active = [r for r in real_estate if is_active(r)]

    bodies = Counter(r[body_col].strip() for r in real_estate)
    institutions = Counter()
    for name, n in bodies.items():
        if re.search(r"bilježni", name, re.I):
            name = "(javni bilježnik)"
        elif re.search(r"upravitelj", name, re.I):
            name = "(stečajni upravitelj)"
        elif not INSTITUTION.search(name):
            name = "(ostalo – nije institucija)"
        institutions[name] += n
    region_bodies = {k: v for k, v in institutions.items() if REGION_COURT.search(k)}

    region_rows = [r for r in real_estate if REGION_COURT.search(r[body_col])]
    region_active = [r for r in region_rows if is_active(r)]

    def ko_counts(subset):
        c = Counter()
        for r in subset:
            for m in KO.finditer(r.get("Opis", "")):
                c[m.group(1).strip()] += 1
        return c

    place_stats = {}
    for place, pattern in PLACES.items():
        rx = re.compile(pattern)
        forms = Counter()
        rows_all = rows_region = 0
        outside_region = 0
        for r in real_estate:
            matches = [m.group(0) for m in rx.finditer(r.get("Opis", ""))]
            if matches:
                rows_all += 1
                forms.update(matches)
                if REGION_COURT.search(r[body_col]):
                    rows_region += 1
                else:
                    outside_region += 1
        place_stats[place] = {
            "redaka_s_pojmom": rows_all,
            "od_toga_sud_u_regiji": rows_region,
            "od_toga_sud_izvan_regije": outside_region,
            "oblici_rijeci": forms.most_common(25),
        }

    desc_lengths = sorted(len(r.get("Opis", "")) for r in real_estate)
    summary = {
        "redaka_ukupno": len(rows),
        "nekretnina": len(real_estate),
        "nekretnina_aktivnih": len(active),
        "zaglavlje": header,
        "nadlezna_tijela_top": institutions.most_common(60),
        "nadlezna_tijela_regija": sorted(region_bodies.items(), key=lambda kv: -kv[1]),
        "nekretnina_sud_u_regiji": len(region_rows),
        "nekretnina_sud_u_regiji_aktivnih": len(region_active),
        "regija_gradjevinsko_aktivnih": sum(
            1 for r in region_active if BUILDING_LAND.search(r.get("Opis", ""))
        ),
        "opis_duljina_medijan": desc_lengths[len(desc_lengths) // 2] if desc_lengths else 0,
        "opis_s_oznakom_ko_udio": round(
            sum(1 for r in real_estate if KO.search(r.get("Opis", ""))) / max(len(real_estate), 1), 3
        ),
        "opis_s_povrsinom_udio": round(
            sum(1 for r in real_estate if AREA.search(r.get("Opis", ""))) / max(len(real_estate), 1), 3
        ),
        "ko_regija_top": ko_counts(region_rows).most_common(150),
        "mjesta": place_stats,
        "primjeri_cijena": [
            r.get("Početna cijena za nadmetanje", "") for r in region_active[:8]
        ],
        "primjeri_utvrdjene_vrijednosti": [
            r.get("Utvrđena vrijednost", "") for r in region_active[:8]
        ],
        "nacin_prodaje_regija_aktivni": Counter(
            r.get("Način prodaje", "") for r in region_active
        ).most_common(),
    }
    (OUT / "analysis.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in summary.items() if k != "ko_regija_top"}, ensure_ascii=False, indent=1)[:6000])


if __name__ == "__main__":
    main()
