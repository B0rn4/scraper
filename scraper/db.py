"""Stanje u SQLite datoteci: viđeni oglasi, poslane obavijesti, zdravlje izvora."""

import json
import sqlite3
from pathlib import Path

from .models import HOUSE, LAND, REJECT, Decision, Listing

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    key TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    title TEXT,
    url TEXT,
    kind TEXT,
    price REAL,
    area REAL,
    jls TEXT,
    status TEXT,
    reasons TEXT,
    near_miss INTEGER DEFAULT 0,
    notified_at TEXT,
    notified_price REAL
);
CREATE INDEX IF NOT EXISTS listings_source ON listings(source);
CREATE TABLE IF NOT EXISTS price_history (
    key TEXT NOT NULL,
    seen_at TEXT NOT NULL,
    price REAL
);
CREATE TABLE IF NOT EXISTS health (
    source TEXT PRIMARY KEY,
    last_ok TEXT,
    failures INTEGER DEFAULT 0,
    last_error TEXT,
    alerted INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    message_id INTEGER PRIMARY KEY,
    key TEXT NOT NULL,
    at TEXT
);
CREATE INDEX IF NOT EXISTS messages_key ON messages(key);
CREATE TABLE IF NOT EXISTS podaci (
    key TEXT PRIMARY KEY,
    info TEXT,
    at TEXT
);
CREATE TABLE IF NOT EXISTS muted (
    key TEXT PRIMARY KEY,
    at TEXT,
    note TEXT
);
CREATE TABLE IF NOT EXISTS napomene (
    key TEXT NOT NULL,
    kopija TEXT NOT NULL,
    izvor TEXT,
    url TEXT,
    retci TEXT,
    ne_odgovara INTEGER DEFAULT 0,
    at TEXT,
    PRIMARY KEY (key, kopija)
);
CREATE TABLE IF NOT EXISTS tenders (
    key TEXT PRIMARY KEY,
    site TEXT,
    jls TEXT,
    title TEXT,
    url TEXT,
    published TEXT,
    first_seen TEXT NOT NULL,
    notified_at TEXT
);
"""


class State:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        columns = {r[1] for r in self.conn.execute("PRAGMA table_info(listings)")}
        if "settlement" not in columns:  # dodano za prepoznavanje već viđenih oglasa
            self.conn.execute("ALTER TABLE listings ADD COLUMN settlement TEXT")
        if "category" not in columns:    # kuća za obnovu / nedovršena (usporedba cijena)
            self.conn.execute("ALTER TABLE listings ADD COLUMN category TEXT")
        if "url" not in {r[1] for r in self.conn.execute("PRAGMA table_info(messages)")}:
            self.conn.execute("ALTER TABLE messages ADD COLUMN url TEXT")   # gumb poruke (dopuna: drugi portal)

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()

    # --- oglasi ---

    def get(self, key: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM listings WHERE key = ?", (key,)).fetchone()
        return dict(row) if row else None

    def known_ids(self, source: str) -> set[str]:
        rows = self.conn.execute("SELECT source_id FROM listings WHERE source = ?", (source,))
        return {r[0] for r in rows}

    def known_prices(self, source: str) -> dict[str, float | None]:
        return dict(self.conn.execute("SELECT source_id, price FROM listings WHERE source = ?", (source,)))

    def prune(self, ours: set[str], before_ours: str, before_other: str) -> int:
        """Briše odbijene oglase koji nikad nisu javljeni i dugo se ne pojavljuju: s našeg
        područja kad ispadnu iz usporedbe cijena (before_ours), ostale ranije (before_other).
        Bez toga baza raste bez kraja (Redmi je šalje na GitHub svakih 20 minuta, GitHub
        odbija datoteke veće od 100 MB). Vrati li se takav oglas, obrađuje se kao nov."""
        marks = ",".join("?" * len(ours)) or "''"
        keys = [r[0] for r in self.conn.execute(
            f"""SELECT key FROM listings WHERE status = ? AND notified_at IS NULL AND (
                    (jls IN ({marks}) AND last_seen < ?) OR ((jls IS NULL OR jls NOT IN ({marks})) AND last_seen < ?))""",
            (REJECT, *ours, before_ours, *ours, before_other))]
        for i in range(0, len(keys), 500):
            chunk = keys[i:i + 500]
            q = ",".join("?" * len(chunk))
            self.conn.execute(f"DELETE FROM price_history WHERE key IN ({q})", chunk)
            self.conn.execute(f"DELETE FROM podaci WHERE key IN ({q})", chunk)   # odbijena kopija s dopunom
            self.conn.execute(f"DELETE FROM listings WHERE key IN ({q})", chunk)
        return len(keys)

    def newest(self, source: str) -> str | None:
        """Kad je zadnji put zabilježen nov oglas izvora (nadzor: izvor radi, a ništa novo)."""
        return self.conn.execute("SELECT MAX(first_seen) FROM listings WHERE source = ?", (source,)).fetchone()[0]

    def count(self, source: str) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM listings WHERE source = ?", (source,)).fetchone()[0]

    def upsert(self, listing: Listing, decision: Decision, now: str) -> dict | None:
        """Sprema oglas i vraća prethodni zapis (None ako je oglas nov)."""
        old = self.get(listing.key)
        reasons = json.dumps(decision.reasons + decision.warnings, ensure_ascii=False)
        if old is None:
            self.conn.execute(
                """INSERT INTO listings (key, source, source_id, first_seen, last_seen, title, url, kind,
                   price, area, jls, status, reasons, near_miss, settlement, category)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (listing.key, listing.source, listing.source_id, now, now, listing.title, listing.url,
                 listing.kind, listing.price, listing.area, decision.jls, decision.status, reasons,
                 int(decision.near_miss), listing.settlement, listing.extra.get("kategorija") or None),
            )
        else:
            self.conn.execute(
                # Površina i naselje ostaju ako ih novi dohvat nema (npr. Njuškalo popis bez
                # površine zemljišta, a stranica oglasa otvorena je samo prvi put).
                # Kategorija (za obnovu) ostaje kad je ovaj put samo popis bez opisa; "" (cijeli
                # opis, useljiva) je briše.
                """UPDATE listings SET last_seen = ?, title = ?, url = ?, kind = ?, price = ?, area = COALESCE(?, area),
                   jls = ?, status = ?, reasons = ?, near_miss = ?, settlement = COALESCE(NULLIF(?, ''), settlement),
                   category = COALESCE(?, category)
                   WHERE key = ?""",
                (now, listing.title, listing.url, listing.kind, listing.price, listing.area, decision.jls,
                 decision.status, reasons, int(decision.near_miss), listing.settlement,
                 listing.extra.get("kategorija"), listing.key),
            )
        if old is None or (listing.price is not None and old.get("price") != listing.price):
            self.conn.execute(
                "INSERT INTO price_history (key, seen_at, price) VALUES (?, ?, ?)",
                (listing.key, now, listing.price),
            )
        return old

    def reassess(self, listing: Listing, decision: Decision) -> None:
        """Nova ocjena već zapamćenog oglasa (ponovno otvaranje, runner._reopen) bez dohvata:
        zadnje viđenje, cijena i naslov ostaju."""
        self.conn.execute(
            """UPDATE listings SET kind = ?, area = COALESCE(?, area), jls = ?, status = ?, reasons = ?, near_miss = ?,
               settlement = COALESCE(NULLIF(?, ''), settlement), category = COALESCE(?, category) WHERE key = ?""",
            (listing.kind, listing.area, decision.jls, decision.status,
             json.dumps(decision.reasons + decision.warnings, ensure_ascii=False), int(decision.near_miss),
             listing.settlement, listing.extra.get("kategorija"), listing.key),
        )

    def known_incomplete(self, source: str) -> set[str]:
        """Zapamćene kuće i zemljišta izvora bez površine koji nisu odbijeni (otvaraju se kad se
        pojave na popisu, Source.known_incomplete)."""
        rows = self.conn.execute("SELECT source_id FROM listings WHERE source = ? AND status != ? AND area IS NULL "
                                 "AND kind IN (?, ?)", (source, REJECT, HOUSE, LAND))
        return {r[0] for r in rows}

    def reopen_candidates(self, source: str, since: str) -> list[str]:
        """Zapamćene kuće i zemljišta izvora s našeg područja koji nisu odbijeni, najnoviji prvi."""
        rows = self.conn.execute(
            "SELECT source_id FROM listings WHERE source = ? AND status != ? AND kind IN (?, ?) "
            "AND jls IS NOT NULL AND last_seen >= ? ORDER BY last_seen DESC", (source, REJECT, HOUSE, LAND, since))
        return [r[0] for r in rows]

    def mark_notified(self, key: str, price: float | None, now: str) -> None:
        self.conn.execute(
            "UPDATE listings SET notified_at = ?, notified_price = ? WHERE key = ?", (now, price, key)
        )

    # Izvještaji ne uključuju oglase iz početnog popisa izvora (oni nisu "novi").

    def _baselines(self) -> dict[str, str]:
        rows = self.conn.execute("SELECT key, value FROM meta WHERE key LIKE 'baseline:%'")
        return {key.split(":", 1)[1]: value for key, value in rows}

    def _new_since(self, since: str, where: str = "1=1") -> list[dict]:
        baselines = self._baselines()
        # "tiho:" = stari oglas ponovno objavljen ili početak praćenja; "dup:" = isti oglas
        # već viđen na drugom portalu – nijedan nije nov.
        rows = self.conn.execute(
            f"SELECT * FROM listings WHERE first_seen >= ? AND {where} "
            "AND (notified_at IS NULL OR (notified_at NOT LIKE 'tiho:%' AND notified_at NOT LIKE 'dup:%')) "
            "ORDER BY first_seen", (since,)
        )
        return [dict(r) for r in rows if r["first_seen"] > baselines.get(r["source"], "")]

    def near_misses_since(self, since: str) -> list[dict]:
        return self._new_since(since, "near_miss = 1")

    def notified_since(self, since: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM listings WHERE notified_at >= ? AND notified_at NOT LIKE 'zbirno:%' "
            "AND notified_at NOT LIKE 'tiho:%' AND notified_at NOT LIKE 'dup:%' ORDER BY notified_at",
            (since,),
        )
        return [dict(r) for r in rows]

    # --- "Ne zanima me" (gumb ispod poruke) ---

    def mute(self, key: str, at: str, note: str = "") -> None:
        self.conn.execute("INSERT OR IGNORE INTO muted (key, at, note) VALUES (?, ?, ?)", (key, at, note))

    def remember_message(self, message_id: int, key: str, at: str, url: str = "") -> None:
        """Poruka s oglasom: reakcija 👎 nosi samo broj poruke, ne oglas. url: gumb poruke (kod dopune
        to je oglas s drugog portala) – nakon 👎 gumb ostaje isti."""
        self.conn.execute("INSERT OR REPLACE INTO messages (message_id, key, at, url) VALUES (?, ?, ?, ?)",
                          (message_id, key, at, url or None))

    def message_url(self, message_id: int) -> str | None:
        row = self.conn.execute("SELECT url FROM messages WHERE message_id = ?", (message_id,)).fetchone()
        return row[0] if row else None

    def set_info(self, key: str, info: dict, at: str) -> None:
        """Što je poslana poruka (ili dopuna) rekla o oglasu – za dopunu s drugog portala."""
        self.conn.execute("INSERT OR REPLACE INTO podaci (key, info, at) VALUES (?, ?, ?)",
                          (key, json.dumps(info, ensure_ascii=False), at))

    def add_note(self, key: str, copy: str, source: str, url: str, lines: list[str], mismatch: bool, at: str) -> None:
        """Napomena uz oglas iz datoteke s popisom: što je isti oglas na drugom portalu (`copy`)
        donio – retci kao u dopuni; mismatch: prema tom portalu ne odgovara kriterijima."""
        self.conn.execute("INSERT OR REPLACE INTO napomene (key, kopija, izvor, url, retci, ne_odgovara, at) "
                          "VALUES (?, ?, ?, ?, ?, ?, ?)",
                          (key, copy, source, url, json.dumps(lines, ensure_ascii=False), int(mismatch), at))

    def notes(self) -> dict[str, list[dict]]:
        """Napomene po oglasu iz datoteke s popisom (završni pregled: report.entry(..., notes))."""
        out: dict[str, list[dict]] = {}
        for r in self.conn.execute("SELECT * FROM napomene ORDER BY at, kopija"):
            out.setdefault(r["key"], []).append({"kopija": r["kopija"], "izvor": r["izvor"], "url": r["url"],
                                                 "retci": json.loads(r["retci"] or "[]"),
                                                 "ne_odgovara": bool(r["ne_odgovara"]), "at": r["at"]})
        return out

    def message_key(self, message_id: int) -> str | None:
        row = self.conn.execute("SELECT key FROM messages WHERE message_id = ?", (message_id,)).fetchone()
        return row[0] if row else None

    def unmute(self, key: str) -> None:
        """Poništenje: oglas i isti oglasi na drugim portalima zapamćeni zbog njega – i
        njihove kopije (lanac "isti kao B", a B "isti kao A")."""
        keys, todo = set(), [key]
        while todo:
            k = todo.pop()
            if k not in keys:
                keys.add(k)
                todo += [r[0] for r in self.conn.execute("SELECT key FROM muted WHERE note = ?", (f"isti kao {k}",))]
        self.conn.executemany("DELETE FROM muted WHERE key = ?", [(k,) for k in keys])

    def muted(self, remote: set[str] | None = None) -> set[str]:
        """Utišani oglasi. S popisom s drugog uređaja (Redmi dobiva popis s GitHuba): taj
        popis i ovdje zapamćeni isti oglasi samo dok je njihov izvorni oglas na popisu –
        poništenje na GitHubu tako vrijedi i ovdje."""
        rows = self.conn.execute("SELECT key, note FROM muted").fetchall()
        if remote is None:
            return {r[0] for r in rows}
        return set(remote) | {r[0] for r in rows if (r[1] or "").removeprefix("isti kao ") in remote}

    def seen_rows(self) -> list[dict]:
        """Oglasi koje smo već "vidjeli" (poslani, u početnom popisu ili tiho zabilježeni)."""
        rows = self.conn.execute(
            "SELECT l.key, source, kind, jls, price, area, title, settlement, notified_at, notified_price, "
            # Za dopunu: što je poruka rekla i njen broj (odgovor na nju).
            "p.info AS podaci, (SELECT MIN(message_id) FROM messages m WHERE m.key = l.key) AS poruka, status, "
            "l.url "                                       # gumb za stariji oglas ("📉 Već viđen …")
            # I bez cijene ("cijena na upit"): isti oglas na upit s drugog portala ne smije stići ponovno.
            "FROM listings l LEFT JOIN podaci p ON p.key = l.key "
            "WHERE notified_at IS NOT NULL AND area IS NOT NULL AND jls IS NOT NULL"
        )
        return [dict(r) for r in rows]

    def price_rows(self) -> list[dict]:
        """Svi oglasi s cijenom i površinom (medijan traženih cijena, prosjek područja)."""
        rows = self.conn.execute(
            "SELECT key, kind, jls, price, area, title, settlement, reasons, status, category, last_seen, notified_at "
            "FROM listings WHERE price IS NOT NULL AND area IS NOT NULL AND jls IS NOT NULL"
        )
        return [dict(r) for r in rows]

    def duplicates_since(self, since: str) -> list[dict]:
        """Preskočeni kao već viđeni. Odbijena kopija s ⚠ dopunom ili napomenom također je "isti
        kao" (da se ⚠ ne ponavlja), ali nije preskočena – odbijena je."""
        rows = self.conn.execute(
            "SELECT * FROM listings WHERE first_seen >= ? AND notified_at LIKE 'dup:%' AND status != ? "
            "ORDER BY first_seen", (since, REJECT)
        )
        return [dict(r) for r in rows]

    def counts_since(self, since: str) -> dict[str, dict[str, int]]:
        """Novi oglasi po izvoru i odluci (bez istih kao već viđeni). Oglas s brojem do najvećeg na
        početku praćenja objavljen je prije (agencije ga ponovno objave pod starim brojem): ne broji
        se među nove, nego pod "stari" – samo ako odgovara."""
        baselines, tops, out = self._baselines(), {}, {}
        rows = self.conn.execute("SELECT source, source_id, status, notified_at, first_seen FROM listings WHERE "
                                 "first_seen >= ? AND (notified_at IS NULL OR notified_at NOT LIKE 'dup:%')", (since,))
        for r in rows:
            if r["first_seen"] <= baselines.get(r["source"], ""):
                continue
            if r["source"] not in tops:
                tops[r["source"]] = self.start_max_id(r["source"])
            top, counts = tops[r["source"]], out.setdefault(r["source"], {})
            if top is not None and str(r["source_id"]).isdigit() and int(r["source_id"]) <= top:
                if r["status"] != REJECT:
                    counts["stari"] = counts.get("stari", 0) + 1
            elif not (r["notified_at"] or "").startswith("tiho:"):
                counts[r["status"]] = counts.get(r["status"], 0) + 1
        return out

    def start_max_id(self, source: str) -> int | None:
        """Najveći broj oglasa izvora na početku praćenja: oglas s manjim brojem objavljen je prije
        (Njuškalo, index.hr: osvježeni stari oglasi zadržavaju broj). Pamti se, jer se odbijeni
        oglasi s početka s vremenom brišu (prune). Bez neobično velikog broja (druga numeracija)."""
        key = f"pocetni_broj:{source}"
        if self.meta_get(key):
            return int(self.meta_get(key))
        start = self.meta_get(f"baseline:{source}")
        ids = sorted((int(r[0]) for r in self.conn.execute(
            "SELECT source_id FROM listings WHERE source = ? AND first_seen <= ? AND source_id GLOB '[0-9]*' "
            "AND source_id NOT GLOB '*[^0-9]*'", (source, start or ""))), reverse=True)
        if not start or not ids:
            return None
        median = ids[:50][len(ids[:50]) // 2]
        top = max(i for i in ids if i <= median * 1.05)
        self.meta_set(key, str(top))
        return top

    # --- zdravlje izvora ---

    def health_ok(self, source: str, now: str) -> int:
        """Bilježi uspjeh; vraća broj grešaka zaredom prije ovog uspjeha."""
        row = self.conn.execute("SELECT failures FROM health WHERE source = ?", (source,)).fetchone()
        previous = row[0] if row else 0
        self.conn.execute(
            """INSERT INTO health (source, last_ok, failures, last_error, alerted) VALUES (?, ?, 0, NULL, 0)
               ON CONFLICT(source) DO UPDATE SET last_ok = excluded.last_ok, failures = 0, alerted = 0""",
            (source, now),
        )
        return previous

    def health_fail(self, source: str, error: str) -> tuple[int, bool]:
        """Bilježi grešku; vraća (broj grešaka zaredom, je li upozorenje već poslano)."""
        self.conn.execute(
            """INSERT INTO health (source, failures, last_error) VALUES (?, 1, ?)
               ON CONFLICT(source) DO UPDATE SET failures = failures + 1, last_error = excluded.last_error""",
            (source, error[:1000]),
        )
        row = self.conn.execute("SELECT failures, alerted FROM health WHERE source = ?", (source,)).fetchone()
        return row[0], bool(row[1])

    def mark_alerted(self, source: str) -> None:
        self.conn.execute("UPDATE health SET alerted = 1 WHERE source = ?", (source,))

    def health_all(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM health ORDER BY source")]

    # --- natječaji (faza 4) ---

    def tender_known(self, key: str) -> bool:
        return self.conn.execute("SELECT 1 FROM tenders WHERE key = ?", (key,)).fetchone() is not None

    def tender_add(self, tender, now: str, notified_at: str | None) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO tenders (key, site, jls, title, url, published, first_seen, notified_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (tender.key, tender.site, tender.jls, tender.title, tender.url, tender.published, now, notified_at))

    # --- razno ---

    def meta_get(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def meta_set(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
