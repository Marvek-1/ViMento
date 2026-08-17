"""SQLite mirror of the paper-trading file ledger.

The files under ``agent/paper_sessions/<id>/`` (``session.json``,
``book.json``, ``marks.jsonl``, ``trades.jsonl``) remain the source of
truth -- receipted and tamper-evident via ``write_receipt.py``. This store
is a queryable mirror written alongside them, not a replacement: if this
database were deleted entirely, every session would still be fully
readable from disk. Same plain-sqlite3 pattern as
``agent/src/goal/store.py`` -- no new DB technology.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path.home() / ".vibe-trading" / "paper.db"
_DB_PATH_ENV = "VIBE_PAPER_DB_PATH"


def _default_db_path() -> Path:
    raw_path = os.getenv(_DB_PATH_ENV, "").strip()
    if raw_path:
        return Path(raw_path).expanduser()
    return _DEFAULT_DB_PATH


F = TypeVar("F", bound=Callable)


def _synchronized(method: F) -> F:
    """Serialize access to the shared SQLite connection."""

    @wraps(method)
    def wrapper(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper  # type: ignore[return-value]


class PaperStore:
    """SQLite-backed mirror for paper-trading sessions, marks, and trades."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else _default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._lock = threading.RLock()
        self._init_db()

    def _retry_write(self, query: str, params: tuple = (), max_retries: int = 3) -> sqlite3.Cursor:
        """Execute a write with exponential backoff on 'database is locked'."""
        for attempt in range(max_retries):
            try:
                cur = self._conn.execute(query, params)
                self._conn.commit()
                return cur
            except sqlite3.OperationalError as exc:
                if "database is locked" in str(exc) and attempt < max_retries - 1:
                    wait = 0.1 * (2 ** attempt)
                    logger.warning("paper_store: database locked, retry %d/%d after %.1fs", attempt + 1, max_retries, wait)
                    time.sleep(wait)
                    continue
                logger.critical("paper_store: write failed after %d retries: %s", max_retries, exc)
                raise
        raise RuntimeError("unreachable")

    def _init_db(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS paper_sessions (
                    session_id TEXT PRIMARY KEY,
                    strategy_type TEXT NOT NULL,
                    symbols_json TEXT NOT NULL,
                    initial_cash REAL NOT NULL,
                    entry_time TEXT NOT NULL,
                    rebalance_interval_hours REAL,
                    fee_rate REAL NOT NULL DEFAULT 0,
                    source TEXT,
                    price_kind TEXT,
                    fees_modeled INTEGER NOT NULL DEFAULT 0,
                    slippage_modeled INTEGER NOT NULL DEFAULT 0,
                    cash_accounting_note TEXT
                );

                CREATE TABLE IF NOT EXISTS paper_marks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES paper_sessions(session_id),
                    timestamp TEXT NOT NULL,
                    prices_json TEXT NOT NULL,
                    position_values_json TEXT NOT NULL,
                    cash_remaining REAL NOT NULL,
                    equity REAL NOT NULL,
                    pnl REAL NOT NULL,
                    pnl_pct REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_paper_marks_session
                    ON paper_marks(session_id, timestamp);

                CREATE TABLE IF NOT EXISTS paper_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES paper_sessions(session_id),
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    qty REAL NOT NULL,
                    price REAL NOT NULL,
                    notional REAL NOT NULL,
                    fee_paid REAL NOT NULL DEFAULT 0,
                    reason TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_paper_trades_session
                    ON paper_trades(session_id, timestamp);
                """
            )
            self._conn.commit()

    @_synchronized
    def upsert_session(
        self,
        session_id: str,
        session: dict[str, Any],
        cash_accounting_note: str | None = None,
    ) -> None:
        """Insert a session row, or update just its accounting note if it already exists.

        Session config (symbols, initial cash, fee rate, ...) is written
        once at entry and never changes after -- only ``cash_accounting_note``
        is ever revised later, e.g. to retroactively flag a session as
        pre-dating a bugfix.
        """
        self._retry_write(
            """
            INSERT INTO paper_sessions
                (session_id, strategy_type, symbols_json, initial_cash, entry_time,
                 rebalance_interval_hours, fee_rate, source, price_kind,
                 fees_modeled, slippage_modeled, cash_accounting_note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET cash_accounting_note = excluded.cash_accounting_note
            """,
            (
                session_id,
                session["strategy_type"],
                json.dumps(session["symbols"]),
                session["initial_cash"],
                session["entry_time"],
                session.get("rebalance_interval_hours"),
                session.get("fee_rate", 0.0),
                session.get("source"),
                session.get("price_kind"),
                int(bool(session.get("fees_modeled"))),
                int(bool(session.get("slippage_modeled"))),
                cash_accounting_note,
            ),
        )

    @_synchronized
    def set_cash_accounting_note(self, session_id: str, note: str | None) -> None:
        self._retry_write(
            "UPDATE paper_sessions SET cash_accounting_note = ? WHERE session_id = ?",
            (note, session_id),
        )

    @_synchronized
    def insert_mark(self, session_id: str, mark: dict[str, Any]) -> None:
        self._retry_write(
            """
            INSERT INTO paper_marks
                (session_id, timestamp, prices_json, position_values_json,
                 cash_remaining, equity, pnl, pnl_pct)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                mark["timestamp"],
                json.dumps(mark["prices"]),
                json.dumps(mark["position_values"]),
                mark["cash_remaining"],
                mark["equity"],
                mark["pnl"],
                mark["pnl_pct"],
            ),
        )

    @_synchronized
    def insert_trade(self, session_id: str, trade: dict[str, Any]) -> None:
        self._retry_write(
            """
            INSERT INTO paper_trades
                (session_id, timestamp, symbol, side, qty, price, notional, fee_paid, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                trade["timestamp"],
                trade["symbol"],
                trade["side"],
                trade["qty"],
                trade["price"],
                trade["notional"],
                trade.get("fee_paid", 0.0) or 0.0,
                trade["reason"],
            ),
        )

    @_synchronized
    def get_session(self, session_id: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM paper_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        return dict(row) if row else None

    @_synchronized
    def get_trades(self, session_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM paper_trades WHERE session_id = ? ORDER BY id", (session_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    @_synchronized
    def get_marks(self, session_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM paper_marks WHERE session_id = ? ORDER BY id", (session_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    @_synchronized
    def list_sessions(self, strategy_type: str | None = None) -> list[dict[str, Any]]:
        """Return all stored sessions, optionally filtered by strategy_type."""
        query = "SELECT * FROM paper_sessions"
        params: tuple[Any, ...] = ()
        if strategy_type:
            query += " WHERE strategy_type = ?"
            params = (strategy_type,)
        query += " ORDER BY session_id"
        rows = self._conn.execute(query, params).fetchall()
        sessions = []
        for row in rows:
            s = dict(row)
            s["symbols"] = json.loads(s.pop("symbols_json", "[]"))
            s["fees_modeled"] = bool(s.get("fees_modeled", 0))
            s["slippage_modeled"] = bool(s.get("slippage_modeled", 0))
            sessions.append(s)
        return sessions

    @_synchronized
    def list_trades(self, session_id: str) -> list[dict[str, Any]]:
        return self.get_trades(session_id)

    @_synchronized
    def list_marks(self, session_id: str) -> list[dict[str, Any]]:
        """Return marks for a session with parsed prices/position_values dicts."""
        rows = self._conn.execute(
            "SELECT * FROM paper_marks WHERE session_id = ? ORDER BY id", (session_id,)
        ).fetchall()
        marks = []
        for r in rows:
            m = dict(r)
            m["prices"] = json.loads(m.pop("prices_json", "{}"))
            m["position_values"] = json.loads(m.pop("position_values_json", "{}"))
            marks.append(m)
        return marks

    def close(self) -> None:
        self._conn.close()


_store: Optional[PaperStore] = None


def get_store() -> PaperStore:
    """Return the shared paper-trading store, creating it on first use."""
    global _store
    if _store is None:
        _store = PaperStore()
    return _store
