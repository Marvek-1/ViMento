#!/usr/bin/env python3
"""Backfill per-leg positions from authoritative FuturesPaperEngine state."""
import json, os
from datetime import datetime, timezone
from pathlib import Path
import psycopg

ROOT = Path(__file__).resolve().parents[1]
SESSIONS = {"grid_futures_5x": "grid_futures_5x_v3", "grid_futures_10x": "grid_futures_10x_v3"}
dsn = os.getenv("VIBE_PAPER_DATABASE_URL", "dbname=idim_ikang port=5433")
with psycopg.connect(dsn) as conn, conn.cursor() as cur:
    for worker, session in SESSIONS.items():
        state = json.loads((ROOT / "paper_sessions" / session / "account.json").read_text())
        cur.execute("SELECT account_id,strategy_id,mode FROM paper_trading.trading_accounts WHERE worker_id=%s", (worker,))
        account_id,strategy_id,mode = cur.fetchone()
        legs = list(state["positions"].values())
        for leg in legs:
            cur.execute("""INSERT INTO paper_trading.positions_v2(account_id,trade_id,strategy_id,worker_id,symbol,quantity,average_entry_price,margin_used,unrealized_pnl,updated_at,mode)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,0,%s,%s)
                           ON CONFLICT (account_id,trade_id) DO UPDATE SET quantity=excluded.quantity,average_entry_price=excluded.average_entry_price,margin_used=excluded.margin_used,updated_at=excluded.updated_at""",
                        (account_id,leg["trade_id"],strategy_id,worker,leg["symbol"],leg["quantity"],leg["entry_price"],leg["isolated_margin"],datetime.now(timezone.utc),mode))
        ids=[leg["trade_id"] for leg in legs]
        cur.execute("DELETE FROM paper_trading.positions_v2 WHERE account_id=%s AND NOT (trade_id=ANY(%s))", (account_id,ids)) if ids else cur.execute("DELETE FROM paper_trading.positions_v2 WHERE account_id=%s", (account_id,))
        print(worker, len(legs))
