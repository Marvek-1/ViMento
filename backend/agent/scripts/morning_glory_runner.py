#!/usr/bin/env python3
"""Run Morning Glory as an isolated funding-rate z-score paper worker."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

SCRIPTS_DIR = Path(__file__).resolve().parent
AGENT_DIR = SCRIPTS_DIR.parent
sys.path.insert(0, str(AGENT_DIR))

from futures_paper_engine import (  # noqa: E402
    FuturesPaperEngine, RiskConfig, fetch_funding_history, fetch_funding_rate,
    funding_event_id, read_jsonl,
)
from morning_glory_strategy import decide, funding_zscore  # noqa: E402
from paper_postgres import PaperPostgres, WorkerIdentity  # noqa: E402
from paper_session import _update_heartbeat, fetch_last_prices_with_source  # noqa: E402


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(session_dir: Path, poll_seconds: int, identity: WorkerIdentity) -> None:
    config = json.loads((session_dir / "session_config.json").read_text(encoding="utf-8"))
    manifest = json.loads((AGENT_DIR / "config" / "paper_accounts.json").read_text(encoding="utf-8"))
    account_config = next(
        (row for row in manifest["accounts"] if row["worker_id"] == identity.worker_id), None
    )
    if account_config is None:
        raise RuntimeError(f"worker {identity.worker_id} is missing from paper_accounts.json")
    configured_capital = float(os.getenv(account_config["capital_env"], account_config["initial_capital"]))
    if configured_capital != float(config["initial_balance"]):
        raise RuntimeError("Morning Glory session capital does not match its dedicated account")
    if int(config["leverage"]) != identity.leverage:
        raise RuntimeError("Morning Glory leverage does not match its database identity")

    symbol = str(config["symbol"])
    engine = FuturesPaperEngine(session_dir, initial_balance=configured_capital)
    postgres = PaperPostgres(identity)
    risk = RiskConfig(
        leverage=identity.leverage,
        margin=float(config["margin_per_trade"]),
        take_profit_pct=float(config["take_profit_pct"]),
        stop_loss_pct=float(config["stop_loss_pct"]),
        max_hold_minutes=int(config["max_hold_minutes"]),
    )
    risk.validate(require_max_hold=True)
    last_funding_window: str | None = None

    try:
        while True:
            _update_heartbeat(session_dir)
            cycle_started = datetime.now(timezone.utc)
            try:
                price_result = fetch_last_prices_with_source([symbol])
                price = price_result.prices.get(symbol)
                event_count_before = len(read_jsonl(engine.events_path))
                current_rate = fetch_funding_rate(symbol, source=price_result.source)
                history = fetch_funding_history(
                    symbol,
                    int(config["z_window"]) + 50,
                    source=price_result.source,
                )
                score = funding_zscore(history, current_rate, int(config["z_window"]))
                position = next(iter(engine.state.positions.values()), None)
                decision = decide(
                    score, position is not None,
                    float(config["entry_z"]), float(config["exit_z"]),
                )
                order_rejection = None
                entries_enabled = os.getenv("NEW_ENTRIES_ENABLED", "false").lower() == "true"
                if price is None or price <= 0:
                    order_rejection = "market feed unavailable"
                elif decision.action in {"OPEN_LONG", "OPEN_SHORT"} and position is None:
                    if entries_enabled:
                        engine.open_position(
                            symbol,
                            "long" if decision.action == "OPEN_LONG" else "short",
                            price=price,
                            risk=risk,
                            signal_reason=decision.reason,
                            market_regime="funding_mean_reversion",
                        )
                    else:
                        order_rejection = "entry_gate_disabled"
                elif decision.action == "CLOSE" and position is not None:
                    engine.close_position(
                        position.trade_id, price=price,
                        exit_reason="funding_zscore_mean_reversion", order_type="taker",
                    )

                funding_events: list[dict[str, object]] = []
                if cycle_started.hour in (0, 8, 16):
                    window = cycle_started.strftime("%Y-%m-%dT%H:00:00Z")
                    if window != last_funding_window:
                        for open_position in list(engine.state.positions.values()):
                            payment = engine.apply_funding(
                                open_position.trade_id, current_rate,
                                event_id=funding_event_id(open_position.symbol, window),
                            )
                            funding_events.append({
                                "symbol": open_position.symbol,
                                "funding_timestamp": window,
                                "funding_rate": current_rate,
                                "funding_pnl": -payment,
                            })
                        last_funding_window = window

                prices = {symbol: price} if price else {}
                closed = engine.process_all(
                    prices,
                    market_data_source=price_result.source,
                    market_data_observed_at=_now_iso(),
                )
                snapshot = engine.account_summary(prices)
                cycle_events = read_jsonl(engine.events_path)[event_count_before:]
                opened = sum(1 for event in cycle_events if event.get("event") == "position_opened")
                closed_count = sum(1 for event in cycle_events if event.get("event") == "position_closed")
                entry_requested = decision.action in {"OPEN_LONG", "OPEN_SHORT"}
                rejection_reasons = ({decision.reason: 1} if decision.action == "HOLD" else {})
                if order_rejection:
                    rejection_reasons[order_rejection] = rejection_reasons.get(order_rejection, 0) + 1
                funnel = {
                    "cycles_started": 1,
                    "cycles_completed": 1,
                    "symbols_available": 1 if price else 0,
                    "symbols_scanned": 1 if price else 0,
                    "bars_received": 1 if price else 0,
                    "bars_rejected_stale": 0 if price else 1,
                    "indicators_computed": 1,
                    "signals_evaluated": 1,
                    "signals_true": 1 if entry_requested else 0,
                    "signals_false": 0 if entry_requested else 1,
                    "entries_requested": 1 if entry_requested else 0,
                    "entries_rejected_risk": 0,
                    "entries_rejected_cooldown": 0,
                    "entries_rejected_position_limit": 0,
                    "entries_rejected_session": 1 if entry_requested and not entries_enabled else 0,
                    "entries_rejected_duplicate": 0,
                    "entries_rejected_other": 1 if order_rejection and order_rejection != "entry_gate_disabled" else 0,
                    "paper_orders_submitted": opened,
                    "paper_orders_filled": opened,
                    "positions_opened": opened,
                    "positions_closed": closed_count,
                    "last_cycle_at": snapshot["timestamp"],
                    "last_signal_at": _now_iso() if entry_requested else None,
                    "last_order_attempt_at": _now_iso() if opened else None,
                    "last_fill_at": _now_iso() if opened else None,
                    "last_close_at": _now_iso() if closed_count else None,
                    "rejection_reasons": rejection_reasons,
                }
                postgres.sync_tick(
                    engine.state, snapshot, os.getpid(),
                    funding_events=funding_events,
                    execution_events=cycle_events,
                    cycle_started_at=cycle_started,
                    market_data_source=price_result.source,
                    market_data_fresh=bool(price),
                    cycle_diagnostics={
                        "signal_score": score,
                        "entry_threshold": float(config["entry_z"]),
                        "market_data_age": 0.0 if price else None,
                        "volatility": None,
                        "spread": None,
                        "risk_rejection_reason": None,
                        "strategy_rejection_reason": decision.reason if decision.action == "HOLD" else None,
                        "order_rejection_reason": order_rejection,
                        "decision_funnel": funnel,
                    },
                )
                print(json.dumps({
                    "event": "morning_glory_cycle",
                    "timestamp": snapshot["timestamp"],
                    "funding_rate": current_rate,
                    "signal_score": score,
                    "decision": decision.action,
                    "reason": decision.reason,
                    "open_positions": len(snapshot["open_positions"]),
                    "closed_this_cycle": len(closed),
                    "equity": snapshot["current_equity"],
                    "market_source": price_result.source,
                }), flush=True)
            except KeyboardInterrupt:
                break
            except Exception as exc:  # transient exchange/database failures must not kill worker
                print(json.dumps({
                    "event": "morning_glory_poll_error", "error": str(exc),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }), flush=True)

            remaining = max(1, poll_seconds)
            while remaining:
                sleep_for = min(5, remaining)
                time.sleep(sleep_for)
                remaining -= sleep_for
            try:
                postgres.heartbeat(os.getpid())
                _update_heartbeat(session_dir)
            except Exception as exc:
                    print(json.dumps({"event": "heartbeat_error", "error": str(exc)}), flush=True)
    finally:
        postgres.close()
        engine.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-dir", required=True, type=Path)
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--account-id", required=True, type=UUID)
    parser.add_argument("--strategy-id", required=True)
    parser.add_argument("--timeframe", required=True)
    parser.add_argument("--mode", default="paper", choices=["paper", "live"])
    parser.add_argument("--leverage", required=True, type=int, choices=[5, 10])
    parser.add_argument("--poll-seconds", default=60, type=int)
    args = parser.parse_args()
    run(args.session_dir.resolve(), args.poll_seconds, WorkerIdentity(
        args.account_id, args.strategy_id, args.worker_id,
        args.timeframe, args.mode, args.leverage,
    ))


if __name__ == "__main__":
    main()
