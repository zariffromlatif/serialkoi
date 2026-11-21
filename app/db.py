"""SQLite storage. One connection guarded by a lock; fine for a single-server deployment."""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS chambers (
    id          INTEGER PRIMARY KEY,
    code        TEXT UNIQUE NOT NULL,
    name        TEXT NOT NULL,
    doctor      TEXT NOT NULL,
    area        TEXT NOT NULL DEFAULT '',
    pin_hash    TEXT NOT NULL,
    fee         REAL NOT NULL DEFAULT 5,
    avg_minutes REAL NOT NULL DEFAULT 8,
    alert_ahead INTEGER NOT NULL DEFAULT 3,
    is_open     INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tickets (
    id          INTEGER PRIMARY KEY,
    chamber_id  INTEGER NOT NULL REFERENCES chambers(id),
    day         TEXT NOT NULL,
    serial      INTEGER NOT NULL,
    phone       TEXT,
    name        TEXT,
    source      TEXT NOT NULL,              -- ussd | sms | walkin
    status      TEXT NOT NULL,              -- waiting | called | done | skipped | cancelled
    priority    INTEGER NOT NULL DEFAULT 0, -- 1 = recalled no-show, goes to the front
    alerted     INTEGER NOT NULL DEFAULT 0,
    paid_amount REAL NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    called_at   TEXT,
    finished_at TEXT,
    UNIQUE (chamber_id, day, serial)
);
CREATE INDEX IF NOT EXISTS tickets_queue ON tickets (chamber_id, day, status);
CREATE INDEX IF NOT EXISTS tickets_phone ON tickets (phone, day);
CREATE TABLE IF NOT EXISTS payments (
    id          INTEGER PRIMARY KEY,
    ext_trx_id  TEXT UNIQUE NOT NULL,
    phone       TEXT NOT NULL,
    chamber_id  INTEGER NOT NULL REFERENCES chambers(id),
    source      TEXT NOT NULL,
    amount      REAL NOT NULL,
    reference   TEXT,                       -- requestCorrelator from step 1 (referenceNo for step 2)
    internal_trx_id TEXT,                   -- Applink's id, for support
    status      TEXT NOT NULL,              -- pending | otp | paid | partial | failed | unknown
    attempts    INTEGER NOT NULL DEFAULT 0,
    ticket_id   INTEGER,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ussd_sessions (
    session_id  TEXT PRIMARY KEY,
    phone       TEXT NOT NULL,
    state       TEXT NOT NULL,
    data        TEXT NOT NULL DEFAULT '{}',
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY,
    direction   TEXT NOT NULL,              -- out | in
    kind        TEXT NOT NULL,              -- sms | ussd | otp | report | charge
    address     TEXT,
    body        TEXT,
    status      TEXT,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS seen_callbacks (
    kind        TEXT NOT NULL,
    key         TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (kind, key)
);
CREATE TABLE IF NOT EXISTS sim_otps (
    reference   TEXT PRIMARY KEY,
    phone       TEXT NOT NULL,
    otp         TEXT NOT NULL,
    ext_trx_id  TEXT NOT NULL,
    amount      REAL NOT NULL,
    used        INTEGER NOT NULL DEFAULT 0
);
"""


class Store:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        if path != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
        self.lock = threading.RLock()
        self.conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(payments)")}
        if "internal_trx_id" not in cols:
            self.conn.execute("ALTER TABLE payments ADD COLUMN internal_trx_id TEXT")

    def first_time(self, kind: str, key: str, ts: str) -> bool:
        """Record a callback's dedupe key; False if it was seen before (Applink may redeliver)."""
        if not key:
            return True
        with self.lock:
            try:
                self.conn.execute("INSERT INTO seen_callbacks (kind, key, created_at) VALUES (?,?,?)", (kind, key, ts))
                return True
            except sqlite3.IntegrityError:
                return False

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """A write transaction. Never nest these."""
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield self.conn
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise
            self.conn.execute("COMMIT")

    def all(self, sql: str, args: tuple = ()) -> list[dict[str, Any]]:
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args)]

    def one(self, sql: str, args: tuple = ()) -> dict[str, Any] | None:
        with self.lock:
            row = self.conn.execute(sql, args).fetchone()
            return dict(row) if row else None

    def run(self, sql: str, args: tuple = ()) -> int:
        """Single autocommit statement; returns lastrowid."""
        with self.lock:
            return self.conn.execute(sql, args).lastrowid
