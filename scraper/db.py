"""Stanje u SQLite datoteci: viđeni oglasi, poslane obavijesti, zdravlje izvora."""

import json
import sqlite3
from pathlib import Path

from .models import Decision, Listing

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
"""


class State:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

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

    def count(self, source: str) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM listings WHERE source = ?", (source,)).fetchone()[0]

    def upsert(self, listing: Listing, decision: Decision, now: str) -> dict | None:
        """Sprema oglas i vraća prethodni zapis (None ako je oglas nov)."""
        old = self.get(listing.key)
        reasons = json.dumps(decision.reasons + decision.warnings, ensure_ascii=False)
        if old is None:
            self.conn.execute(
                """INSERT INTO listings (key, source, source_id, first_seen, last_seen, title, url, kind,
                   price, area, jls, status, reasons, near_miss)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (listing.key, listing.source, listing.source_id, now, now, listing.title, listing.url,
                 listing.kind, listing.price, listing.area, decision.jls, decision.status, reasons,
                 int(decision.near_miss)),
            )
        else:
            self.conn.execute(
                """UPDATE listings SET last_seen = ?, title = ?, url = ?, price = ?, area = ?, jls = ?,
                   status = ?, reasons = ?, near_miss = ? WHERE key = ?""",
                (now, listing.title, listing.url, listing.price, listing.area, decision.jls,
                 decision.status, reasons, int(decision.near_miss), listing.key),
            )
        if old is None or (listing.price is not None and old.get("price") != listing.price):
            self.conn.execute(
                "INSERT INTO price_history (key, seen_at, price) VALUES (?, ?, ?)",
                (listing.key, now, listing.price),
            )
        return old

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
        rows = self.conn.execute(
            f"SELECT * FROM listings WHERE first_seen >= ? AND {where} ORDER BY first_seen", (since,)
        )
        return [dict(r) for r in rows if r["first_seen"] > baselines.get(r["source"], "")]

    def near_misses_since(self, since: str) -> list[dict]:
        return self._new_since(since, "near_miss = 1")

    def notified_since(self, since: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM listings WHERE notified_at >= ? AND notified_at NOT LIKE 'zbirno:%' ORDER BY notified_at",
            (since,),
        )
        return [dict(r) for r in rows]

    def counts_since(self, since: str) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for r in self._new_since(since):
            out.setdefault(r["source"], {}).setdefault(r["status"], 0)
            out[r["source"]][r["status"]] += 1
        return out

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

    # --- razno ---

    def meta_get(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def meta_set(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
