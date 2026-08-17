#!/usr/bin/env python3
"""Fail-closed certification for the six active isolated paper workers.

This reads only the immutable engine events and account-scoped PostgreSQL
projection.  It never creates or repairs a trading record.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import psycopg

AGENT_DIR = Path(__file__).resolve().parent.parent
EXPECTED = {
    "control_5m": ("control_5m_futures", 5),
    "control_10m": ("control_10m_futures", 5),
    "control_15m": ("control_15m_futures", 5),
    "candidate_5m": ("candidate_5m_futures", 10),
    "candidate_10m": ("candidate_10m_futures", 10),
    "candidate_15m": ("candidate_15m_futures", 10),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paper-sessions-dir", type=Path, default=AGENT_DIR / "paper_sessions")
    parser.add_argument("--out", type=Path, default=Path("paper_bootstrap_certificate.json"))
    args = parser.parse_args()
    dsn = os.getenv("VIBE_PAPER_DATABASE_URL", "dbname=idim_ikang port=5433")
    rows = []
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        for worker_id, (session_id, leverage) in EXPECTED.items():
            errors: list[str] = []
            trades_path = args.paper_sessions_dir / session_id / "trades.jsonl"
            event_path = args.paper_sessions_dir / session_id / "events.jsonl"
            trades = [line for line in trades_path.read_text().splitlines() if line.strip()] if trades_path.exists() else []
            events = [json.loads(line) for line in event_path.read_text().splitlines() if line.strip()] if event_path.exists() else []
            opened = sum(e.get("event") == "position_opened" for e in events)
            closed = sum(e.get("event") == "position_closed" for e in events)
            cur.execute("""SELECT a.leverage,a.fees,a.realized_pnl,a.ledger_status,
                              count(DISTINCT o.exchange_order_id),count(DISTINCT f.exchange_fill_id)
                           FROM paper_trading.trading_accounts a
                           LEFT JOIN paper_trading.orders o ON o.account_id=a.account_id
                           LEFT JOIN paper_trading.fills f ON f.account_id=a.account_id
                          WHERE a.worker_id=%s AND a.mode='paper'
                          GROUP BY a.leverage,a.fees,a.realized_pnl,a.ledger_status""", (worker_id,))
            db = cur.fetchone()
            if db is None: errors.append("account missing")
            else:
                db_leverage, fees, pnl, ledger, orders, fills = db
                if db_leverage != leverage: errors.append("leverage mismatch")
                if orders < 2: errors.append("orders < 2")
                if fills < 2: errors.append("fills < 2")
                if fees <= 0: errors.append("fees not positive")
                if ledger != "OK": errors.append("ledger not OK")
            if len(trades) < 1: errors.append("closed trades < 1")
            if opened < 1 or closed < 1: errors.append("engine lifecycle incomplete")
            rows.append({"worker_id": worker_id, "session_id": session_id, "leverage": leverage,
                         "passed": not errors, "errors": errors,
                         "engine_closed_trades": len(trades), "engine_open_events": opened,
                         "engine_close_events": closed})
    certificate = {"status": "PASS" if all(r["passed"] for r in rows) else "FAIL",
                   "accounts_expected": 6, "accounts_passed": sum(r["passed"] for r in rows), "workers": rows}
    args.out.write_text(json.dumps(certificate, indent=2), encoding="utf-8")
    print(json.dumps(certificate, indent=2))
    return 0 if certificate["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
