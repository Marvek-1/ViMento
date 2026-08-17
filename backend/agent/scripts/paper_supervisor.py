#!/usr/bin/env python3
"""Read-only Ollama supervisor for committed, reconciled paper cycles."""
from __future__ import annotations

import json
import os
import time
import urllib.request
from uuid import uuid4

import psycopg

DSN = os.getenv("VIBE_PAPER_DATABASE_URL", "dbname=idim_ikang port=5433")
MODEL = os.getenv("OLLAMA_MODEL", "vibe-qwen3-4b-64k:latest")
BASE = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_TIMEOUT_SECONDS = float(os.getenv("SUPERVISOR_OLLAMA_TIMEOUT_SECONDS", "5"))
_ollama_available = True


def deterministic_recommend(row: tuple) -> str:
    """Fail closed from committed facts when the optional LLM is unavailable."""
    if not row[8]:
        return "MARKET_DATA_STALE"
    if not row[16] or row[17] != "COMPLETED":
        return "REVIEW_LEDGER"
    return "CONTINUE"


def recommend(row: tuple) -> str:
    global _ollama_available
    if not _ollama_available:
        return deterministic_recommend(row)
    prompt = ("You are a read-only paper-trading supervisor. Use only these verified facts. "
              "Return exactly one token: CONTINUE, PAUSE_WORKER, REVIEW_LEDGER, or MARKET_DATA_STALE.\n"
              f"worker={row[2]} source={row[7]} fresh={row[8]} reconciled={row[16]} status={row[17]}")
    body = json.dumps({"model": MODEL, "stream": False,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    request = urllib.request.Request(f"{BASE}/api/chat", data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=OLLAMA_TIMEOUT_SECONDS) as response:
            value = json.loads(response.read())["message"]["content"].strip()
        return value if value in {"CONTINUE", "PAUSE_WORKER", "REVIEW_LEDGER", "MARKET_DATA_STALE"} else "REVIEW_LEDGER"
    except Exception as exc:
        _ollama_available = False
        print(json.dumps({
            "event": "supervisor_llm_fallback",
            "error": str(exc),
            "mode": "deterministic",
        }), flush=True)
        return deterministic_recommend(row)


def run_once() -> int:
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("""SELECT id,account_id,worker_id,strategy_id,timeframe,cycle_started_at,cycle_completed_at,
                              market_data_source,market_data_fresh,orders_created,fills_created,trades_closed,
                              realized_pnl,unrealized_pnl,fees,funding_pnl,ledger_reconciled,status,ending_equity
                         FROM paper_trading.paper_cycle_events c
                        WHERE c.market_data_fresh=true AND c.ledger_reconciled=true AND c.status='COMPLETED'
                          AND NOT EXISTS (SELECT 1 FROM paper_trading.trading_notifications n
                                           WHERE n.source_event_id=c.id)
                        ORDER BY cycle_completed_at""")
        rows = cur.fetchall()
        for row in rows:
            advice = recommend(row)
            closed, realized, equity = row[11], float(row[12]), float(row[18])
            event_type = "PROFIT_BANKED" if closed and realized >= 0 else "LOSS_BOOKED" if closed else "NO_TRADE"
            title = f"{row[3]} · {row[4]} cycle complete"
            message = (f"{advice}: Equity ${equity:,.2f}" if closed else
                       f"No trade taken. Verified signal conditions not met. {advice}")
            cur.execute("""INSERT INTO paper_trading.trading_notifications
                           (id,account_id,worker_id,event_type,severity,title,message,source_event_id)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                        (uuid4(), row[1], row[2], event_type, "info", title, message, row[0]))
    return len(rows)


if __name__ == "__main__":
    while True:
        try:
            print(json.dumps({"event": "supervisor_cycle", "processed": run_once()}), flush=True)
        except Exception as exc:
            print(json.dumps({"event": "supervisor_error", "error": str(exc)}), flush=True)
        time.sleep(30)
