"""SQLite store for observer-only IdimIkang market-signal events."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

_DB_PATH_ENV = "VIBE_IDIMIKANG_DB_PATH"
_DEFAULT_DB_PATH = Path.home() / ".vibe-trading" / "idimikang.db"
_TAINT_START = datetime(2026, 7, 5, tzinfo=timezone.utc)
_TAINT_END = datetime(2026, 7, 12, tzinfo=timezone.utc)

F = TypeVar("F", bound=Callable)


def _synchronized(method: F) -> F:
    @wraps(method)
    def wrapper(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper  # type: ignore[return-value]


def _db_path() -> Path:
    raw = os.getenv(_DB_PATH_ENV, "").strip()
    return Path(raw).expanduser() if raw else _DEFAULT_DB_PATH


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, sort_keys=True, default=str)


def _parse_timestamp(value: Any) -> str:
    if value is None or value == "":
        return datetime.now(timezone.utc).isoformat()
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.isdigit():
            raw = int(text)
            dt = datetime.fromtimestamp(raw / 1000 if raw > 10_000_000_000 else raw, tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _tainted_window(timestamp: str) -> bool:
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return False
    return _TAINT_START <= dt < _TAINT_END


def _normalize_direction(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"long", "buy", "bull", "bullish"}:
        return "long"
    if text in {"short", "sell", "bear", "bearish"}:
        return "short"
    return text or "unknown"


def _event_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_json_dumps(payload).encode("utf-8")).hexdigest()


def normalize_event(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize either an Idim scanner row or a canonical ingestion event."""
    source = str(raw.get("source") or "idimikang").strip().lower()
    event_type = str(raw.get("event_type") or "market_signal").strip().lower()
    symbol = str(raw.get("symbol") or raw.get("pair") or "").strip().upper()
    if not symbol:
        raise ValueError("symbol or pair is required")
    timestamp = _parse_timestamp(raw.get("timestamp") or raw.get("ts") or raw.get("created_at"))
    direction = _normalize_direction(raw.get("direction") or raw.get("side"))
    score_value = raw.get("score", 0.0)
    try:
        score = float(score_value)
    except (TypeError, ValueError):
        score = 0.0

    reason_trace = raw.get("reason_trace") or {}
    if isinstance(reason_trace, str):
        try:
            reason_trace = json.loads(reason_trace)
        except json.JSONDecodeError:
            reason_trace = {"raw_reason_trace": reason_trace}

    market_data = raw.get("market_data") or {}
    features = raw.get("features") or {}
    if reason_trace:
        features = {**features, "reason_trace": reason_trace}

    provenance = dict(raw.get("provenance") or {})
    provenance.update(
        {
            "observer_only": True,
            "schema_version": str(provenance.get("schema_version") or "1.0"),
            "tainted_window": bool(provenance.get("tainted_window", _tainted_window(timestamp))),
            "execution_allowed": False,
        }
    )

    normalized = {
        "source": source,
        "event_type": event_type,
        "symbol": symbol,
        "timestamp": timestamp,
        "direction": direction,
        "score": score,
        "timeframe": str(raw.get("timeframe") or raw.get("interval") or "unknown"),
        "market_data": market_data,
        "features": features,
        "provenance": provenance,
        "raw": raw,
    }
    source_event_id = (
        raw.get("source_event_id")
        or raw.get("event_id")
        or raw.get("signal_id")
        or raw.get("id")
        or _event_hash(normalized)
    )
    normalized["source_event_id"] = str(source_event_id)
    normalized["event_hash"] = _event_hash(normalized)
    return normalized


class IdimikangEventStore:
    """SQLite-backed mirror for normalized IdimIkang observer events."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else _db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS idimikang_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_event_id TEXT NOT NULL UNIQUE,
                    event_hash TEXT NOT NULL UNIQUE,
                    source TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    score REAL NOT NULL,
                    timeframe TEXT NOT NULL,
                    market_data_json TEXT NOT NULL,
                    features_json TEXT NOT NULL,
                    provenance_json TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    observer_only INTEGER NOT NULL DEFAULT 1,
                    tainted_window INTEGER NOT NULL DEFAULT 0,
                    received_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_idimikang_events_symbol_ts
                    ON idimikang_events(symbol, timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_idimikang_events_received_at
                    ON idimikang_events(received_at DESC);
                """
            )
            self._conn.commit()

    @_synchronized
    def ingest(self, raw: dict[str, Any]) -> dict[str, Any]:
        event = normalize_event(raw)
        received_at = datetime.now(timezone.utc).isoformat()
        cur = self._conn.execute(
            """
            INSERT OR IGNORE INTO idimikang_events (
                source_event_id, event_hash, source, event_type, symbol,
                timestamp, direction, score, timeframe, market_data_json,
                features_json, provenance_json, raw_json, observer_only,
                tainted_window, received_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event["source_event_id"],
                event["event_hash"],
                event["source"],
                event["event_type"],
                event["symbol"],
                event["timestamp"],
                event["direction"],
                event["score"],
                event["timeframe"],
                _json_dumps(event["market_data"]),
                _json_dumps(event["features"]),
                _json_dumps(event["provenance"]),
                _json_dumps(event["raw"]),
                1,
                int(bool(event["provenance"].get("tainted_window"))),
                received_at,
            ),
        )
        self._conn.commit()
        return {"inserted": cur.rowcount == 1, "event": event}

    @_synchronized
    def list_events(
        self,
        *,
        symbol: str | None = None,
        limit: int = 100,
        include_tainted: bool = True,
    ) -> list[dict[str, Any]]:
        clauses = []
        params: list[Any] = []
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol.upper())
        if not include_tainted:
            clauses.append("tainted_window = 0")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"""
            SELECT * FROM idimikang_events
            {where}
            ORDER BY timestamp DESC, id DESC
            LIMIT ?
            """,
            (*params, int(limit)),
        ).fetchall()
        return [self._row_to_event(row) for row in rows]

    @_synchronized
    def get_all_signals(
        self,
        *,
        limit: int | None = None,
        include_tainted: bool = True,
    ) -> list[dict[str, Any]]:
        """Return the original raw payloads for all emitted signals."""
        clauses: list[str] = []
        params: list[Any] = []
        if not include_tainted:
            clauses.append("tainted_window = 0")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"""
            SELECT raw_json FROM idimikang_events
            {where}
            ORDER BY timestamp DESC, id DESC
            LIMIT ?
            """,
            (*params, int(limit if limit is not None else 1_000_000_000)),
        ).fetchall()
        return [json.loads(row["raw_json"]) for row in rows]

    @_synchronized
    def stats(self) -> dict[str, Any]:
        row = self._conn.execute(
            """
            SELECT
                COUNT(*) AS event_count,
                COUNT(DISTINCT symbol) AS symbol_count,
                SUM(CASE WHEN tainted_window = 1 THEN 1 ELSE 0 END) AS tainted_count,
                MAX(timestamp) AS latest_timestamp
            FROM idimikang_events
            """
        ).fetchone()
        return dict(row) if row else {}

    def _row_to_event(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "source_event_id": row["source_event_id"],
            "source": row["source"],
            "event_type": row["event_type"],
            "symbol": row["symbol"],
            "timestamp": row["timestamp"],
            "direction": row["direction"],
            "score": row["score"],
            "timeframe": row["timeframe"],
            "market_data": json.loads(row["market_data_json"]),
            "features": json.loads(row["features_json"]),
            "provenance": json.loads(row["provenance_json"]),
            "received_at": row["received_at"],
        }

    def close(self) -> None:
        self._conn.close()


_store: Optional[IdimikangEventStore] = None


def get_store() -> IdimikangEventStore:
    global _store
    if _store is None:
        _store = IdimikangEventStore()
    return _store
