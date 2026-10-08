from __future__ import annotations

import sqlite3
import threading
from datetime import date, datetime, timezone
from pathlib import Path

from ticket_watch.models import Event, Watch

SCHEMA = """
CREATE TABLE IF NOT EXISTS watches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    target_price REAL NOT NULL,
    date_from TEXT,
    date_to TEXT,
    quantity INTEGER NOT NULL DEFAULT 1,
    home_only INTEGER NOT NULL DEFAULT 0,
    venue_name TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
-- Latest known state of every event a watch has matched.
CREATE TABLE IF NOT EXISTS tracked_events (
    watch_id INTEGER NOT NULL REFERENCES watches(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    event_id TEXT NOT NULL,
    title TEXT NOT NULL,
    starts_at TEXT NOT NULL,
    venue_name TEXT NOT NULL,
    url TEXT NOT NULL,
    price REAL,
    last_seen TEXT NOT NULL,
    PRIMARY KEY (watch_id, provider, event_id)
);
-- Append-only, written only when a price changes.
CREATE TABLE IF NOT EXISTS price_history (
    provider TEXT NOT NULL,
    event_id TEXT NOT NULL,
    price REAL,
    seen_at TEXT NOT NULL
);
-- The last alert sent per (watch, event); deleted when the price re-arms.
CREATE TABLE IF NOT EXISTS alerts (
    watch_id INTEGER NOT NULL REFERENCES watches(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    event_id TEXT NOT NULL,
    price REAL NOT NULL,
    sent_at TEXT NOT NULL,
    PRIMARY KEY (watch_id, provider, event_id)
);
CREATE TABLE IF NOT EXISTS provider_status (
    provider TEXT PRIMARY KEY,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    last_ok TEXT,
    down_notified INTEGER NOT NULL DEFAULT 0
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _d(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


class Database:
    """Thin sqlite wrapper. One connection shared by the web app and the scheduler thread."""

    def __init__(self, path: str | Path = "ticket_watch.db"):
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.executescript(SCHEMA)

    def _exec(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock, self._conn:
            return self._conn.execute(sql, params)

    def _all(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    # --- watches ---

    def add_watch(self, w: Watch) -> int:
        cur = self._exec(
            "INSERT INTO watches (query, target_price, date_from, date_to, quantity, home_only, venue_name,"
            " active, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                w.query,
                w.target_price,
                w.date_from.isoformat() if w.date_from else None,
                w.date_to.isoformat() if w.date_to else None,
                w.quantity,
                int(w.home_only),
                w.venue_name or None,
                int(w.active),
                _now(),
            ),
        )
        return int(cur.lastrowid)

    def _row_to_watch(self, r: sqlite3.Row) -> Watch:
        return Watch(
            id=r["id"],
            query=r["query"],
            target_price=r["target_price"],
            date_from=_d(r["date_from"]),
            date_to=_d(r["date_to"]),
            quantity=r["quantity"],
            home_only=bool(r["home_only"]),
            venue_name=r["venue_name"],
            active=bool(r["active"]),
        )

    def list_watches(self, active_only: bool = False) -> list[Watch]:
        sql = "SELECT * FROM watches" + (" WHERE active = 1" if active_only else "") + " ORDER BY id"
        return [self._row_to_watch(r) for r in self._all(sql)]

    def get_watch(self, watch_id: int) -> Watch | None:
        rows = self._all("SELECT * FROM watches WHERE id = ?", (watch_id,))
        return self._row_to_watch(rows[0]) if rows else None

    def set_watch_active(self, watch_id: int, active: bool) -> None:
        self._exec("UPDATE watches SET active = ? WHERE id = ?", (int(active), watch_id))

    def delete_watch(self, watch_id: int) -> None:
        self._exec("DELETE FROM watches WHERE id = ?", (watch_id,))

    # --- tracked events & prices ---

    def record_event(self, watch_id: int, e: Event) -> None:
        prev = self._all(
            "SELECT price FROM tracked_events WHERE watch_id = ? AND provider = ? AND event_id = ?",
            (watch_id, e.provider, e.provider_event_id),
        )
        now = _now()
        self._exec(
            "INSERT INTO tracked_events (watch_id, provider, event_id, title, starts_at, venue_name, url, price,"
            " last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (watch_id, provider, event_id) DO UPDATE SET title = excluded.title,"
            " starts_at = excluded.starts_at, venue_name = excluded.venue_name, url = excluded.url,"
            " price = excluded.price, last_seen = excluded.last_seen",
            (
                watch_id,
                e.provider,
                e.provider_event_id,
                e.title,
                e.starts_at.isoformat(),
                e.venue_name,
                e.url,
                e.lowest_price,
                now,
            ),
        )
        if not prev or prev[0]["price"] != e.lowest_price:
            self._exec(
                "INSERT INTO price_history (provider, event_id, price, seen_at) VALUES (?, ?, ?, ?)",
                (e.provider, e.provider_event_id, e.lowest_price, now),
            )

    def tracked_events(self, watch_id: int) -> list[sqlite3.Row]:
        return self._all(
            "SELECT t.*, a.price AS alerted_price FROM tracked_events t LEFT JOIN alerts a"
            " ON a.watch_id = t.watch_id AND a.provider = t.provider AND a.event_id = t.event_id"
            " WHERE t.watch_id = ? AND t.starts_at >= ? ORDER BY t.starts_at, t.provider",
            (watch_id, datetime.now().date().isoformat()),
        )

    # --- alerts ---

    def last_alert_price(self, watch_id: int, provider: str, event_id: str) -> float | None:
        rows = self._all(
            "SELECT price FROM alerts WHERE watch_id = ? AND provider = ? AND event_id = ?",
            (watch_id, provider, event_id),
        )
        return rows[0]["price"] if rows else None

    def record_alert(self, watch_id: int, provider: str, event_id: str, price: float) -> None:
        self._exec(
            "INSERT INTO alerts (watch_id, provider, event_id, price, sent_at) VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT (watch_id, provider, event_id) DO UPDATE SET price = excluded.price,"
            " sent_at = excluded.sent_at",
            (watch_id, provider, event_id, price, _now()),
        )

    def clear_alert(self, watch_id: int, provider: str, event_id: str) -> None:
        self._exec(
            "DELETE FROM alerts WHERE watch_id = ? AND provider = ? AND event_id = ?",
            (watch_id, provider, event_id),
        )

    # --- provider health ---

    def provider_ok(self, provider: str) -> None:
        self._exec(
            "INSERT INTO provider_status (provider, consecutive_failures, last_ok, down_notified)"
            " VALUES (?, 0, ?, 0) ON CONFLICT (provider) DO UPDATE SET consecutive_failures = 0,"
            " last_ok = excluded.last_ok, down_notified = 0",
            (provider, _now()),
        )

    def provider_failed(self, provider: str, error: str) -> sqlite3.Row:
        self._exec(
            "INSERT INTO provider_status (provider, consecutive_failures, last_error) VALUES (?, 1, ?)"
            " ON CONFLICT (provider) DO UPDATE SET consecutive_failures = consecutive_failures + 1,"
            " last_error = excluded.last_error",
            (provider, error),
        )
        return self._all("SELECT * FROM provider_status WHERE provider = ?", (provider,))[0]

    def mark_provider_down_notified(self, provider: str) -> None:
        self._exec("UPDATE provider_status SET down_notified = 1 WHERE provider = ?", (provider,))

    def provider_statuses(self) -> dict[str, sqlite3.Row]:
        return {r["provider"]: r for r in self._all("SELECT * FROM provider_status")}
