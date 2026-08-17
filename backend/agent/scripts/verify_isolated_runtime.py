#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg


AGENT_DIR = Path(__file__).resolve().parent.parent


def main() -> None:
    manifest = json.loads((AGENT_DIR / "config" / "paper_accounts.json").read_text())
    expected = {row["worker_id"]: row for row in manifest["accounts"]}
    dsn = os.getenv("VIBE_PAPER_DATABASE_URL", manifest["database_dsn"])
    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute(
            """SELECT a.worker_id,a.strategy_id,a.timeframe,a.leverage,a.mode,
                      h.last_seen_at,e.equity,
                      (SELECT count(*) FROM paper_trading.positions p
                       WHERE p.account_id=a.account_id)
                 FROM paper_trading.trading_accounts a
                 LEFT JOIN paper_trading.worker_heartbeats h USING (account_id)
                 LEFT JOIN LATERAL (
                     SELECT equity FROM paper_trading.equity_history e
                      WHERE e.account_id=a.account_id ORDER BY marked_at DESC LIMIT 1
                 ) e ON true
                ORDER BY a.strategy_id,a.timeframe"""
        )
        rows = cursor.fetchall()

    seen: set[str] = set()
    now = datetime.now(timezone.utc)
    for worker_id, strategy, timeframe, leverage, mode, last_seen, equity, positions in rows:
        if worker_id not in expected:
            continue
        seen.add(worker_id)
        age = (now - last_seen).total_seconds() if last_seen else float("inf")
        ok = mode == "paper" and leverage in (5, 10) and age <= 300 and equity is not None
        print(
            f"{'PASS' if ok else 'FAIL'}  {worker_id:<15} {strategy:<9} {timeframe:<3} "
            f"{leverage}x equity={equity} positions={positions} heartbeat_age={age:.1f}s"
        )
        if not ok:
            raise SystemExit(1)
    missing = set(expected) - seen
    if missing:
        print(f"FAIL  missing accounts: {sorted(missing)}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
