#!/usr/bin/env python3
"""Poll loop that drives a bounded_grid_v1 paper account.

Same shape as grid_futures_runner.py (real prices in, FuturesPaperEngine owns
every order/fill/fee/position/exit, PaperPostgres publishes the account-scoped
projection) but with grid-specific entry logic from bounded_grid_strategy.py
instead of the frozen-momentum signal, and a 5-second tick instead of a
5/10/15-minute one -- a grid ladder needs to see price cross a level promptly,
not once per candle.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

_SCRIPTS_DIR = Path(__file__).resolve().parent
_AGENT_DIR = _SCRIPTS_DIR.parent
sys.path.insert(0, str(_SCRIPTS_DIR))
sys.path.insert(0, str(_AGENT_DIR))

from futures_paper_engine import FuturesPaperEngine, RiskConfig, read_jsonl  # noqa: E402
from bounded_grid_strategy import BoundedGridConfig, BoundedGridStrategy, config_hash  # noqa: E402
from paper_postgres import PaperPostgres, WorkerIdentity  # noqa: E402
from paper_session import _update_heartbeat, fetch_last_prices_with_source  # noqa: E402


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_state(strategy: BoundedGridStrategy, state_path: Path) -> None:
    if state_path.exists():
        strategy.restore_state(json.loads(state_path.read_text(encoding="utf-8")))


def _save_state(strategy: BoundedGridStrategy, state_path: Path) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(strategy.export_state(), indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(state_path)


def run(session_dir: Path, tick_seconds: int, identity: WorkerIdentity) -> None:
    config = json.loads((session_dir / "session_config.json").read_text(encoding="utf-8"))
    manifest = json.loads((_AGENT_DIR / "config" / "paper_accounts.json").read_text(encoding="utf-8"))
    account_config = next(
        (row for row in manifest["accounts"] if row["worker_id"] == identity.worker_id),
        None,
    )
    if account_config is None:
        raise RuntimeError(f"worker {identity.worker_id} is missing from paper_accounts.json")
    capital_env = account_config["capital_env"]
    configured_capital = float(os.getenv(capital_env, account_config["initial_capital"]))
    if float(config["initial_balance"]) != configured_capital:
        raise RuntimeError(
            f"session capital does not match {capital_env}: "
            f"{config['initial_balance']} != {configured_capital}"
        )
    if int(config["leverage"]) != identity.leverage:
        raise RuntimeError("session leverage does not match worker/database identity")

    grid_config = BoundedGridConfig(
        symbol=config["grid_symbol"],
        leverage=config["leverage"],
        margin_per_level=float(config["margin_per_level"]),
        max_total_notional=float(config["max_total_notional"]),
        levels_per_side=int(config.get("levels_per_side", 3)),
        max_open_levels=int(config.get("max_open_levels", 3)),
        grid_spacing_bps=float(config.get("grid_spacing_bps", 25.0)),
        take_profit_bps=float(config.get("take_profit_bps", 30.0)),
        stop_loss_bps=float(config.get("stop_loss_bps", 90.0)),
    )
    if config.get("strategy_config_hash") and config["strategy_config_hash"] != config_hash(grid_config):
        raise RuntimeError(
            "session_config.json strategy_config_hash does not match the "
            "computed bounded_grid_v1 config hash -- refusing to start with "
            "a config that silently drifted from what was provisioned"
        )

    engine = FuturesPaperEngine(session_dir, initial_balance=config["initial_balance"])
    postgres = PaperPostgres(identity)
    strategy = BoundedGridStrategy(grid_config)
    state_path = session_dir / "grid_strategy_state.json"
    _load_state(strategy, state_path)

    risk = RiskConfig(
        leverage=grid_config.leverage,
        margin=grid_config.margin_per_level,
        take_profit_pct=grid_config.take_profit_bps / 10_000.0,
        stop_loss_pct=grid_config.stop_loss_bps / 10_000.0,
    )

    try:
        while True:
            _update_heartbeat(session_dir)
            try:
                cycle_started_at = datetime.now(timezone.utc)
                price_result = fetch_last_prices_with_source([grid_config.symbol])
                mark_price = price_result.prices.get(grid_config.symbol)
                event_count_before = len(read_jsonl(engine.events_path))

                order_rejection_reason = None
                strategy_rejection_reason = None
                entries_enabled = os.getenv("NEW_ENTRIES_ENABLED", "false").lower() == "true"
                intents_applied = 0
                intents = []
                if mark_price is None or mark_price <= 0:
                    strategy_rejection_reason = "no_market_price"
                else:
                    open_trade_ids = set(engine.state.positions.keys())
                    intents = strategy.on_price_tick(mark_price, open_trade_ids)
                    if not intents:
                        strategy_rejection_reason = (
                            "no_level_crossed" if len(strategy.occupied) < grid_config.max_open_levels
                            else "max_open_levels_reached"
                        )
                    if entries_enabled:
                        for intent in intents:
                            side = "long" if intent.action == "OPEN_LONG" else "short"
                            try:
                                position = engine.open_position(
                                    grid_config.symbol, side,
                                    price=mark_price, risk=risk,
                                    signal_reason=intent.reason, market_regime="grid",
                                )
                                strategy.mark_level_filled(intent.level_id, position.trade_id)
                                intents_applied += 1
                            except (RuntimeError, ValueError) as exc:
                                order_rejection_reason = str(exc)
                    elif intents:
                        strategy_rejection_reason = "entry_gate_disabled"
                    _save_state(strategy, state_path)

                closed = engine.process_all(
                    {grid_config.symbol: mark_price} if mark_price else {},
                    market_data_source=price_result.source if mark_price is not None else "unknown",
                    market_data_observed_at=_now_iso(),
                )
                snapshot = engine.account_summary({grid_config.symbol: mark_price} if mark_price else {})
                cycle_events = read_jsonl(engine.events_path)[event_count_before:]
                rejection_reasons = ({strategy_rejection_reason: 1} if strategy_rejection_reason else {})
                if order_rejection_reason:
                    rejection_reasons[order_rejection_reason] = rejection_reasons.get(order_rejection_reason, 0) + 1
                funnel = {
                    "cycles_started": 1,
                    "cycles_completed": 1,
                    "symbols_available": 1 if mark_price else 0,
                    "symbols_scanned": 1 if mark_price else 0,
                    "bars_received": 1 if mark_price else 0,
                    "bars_rejected_stale": 0 if mark_price else 1,
                    "indicators_computed": 0,
                    "signals_evaluated": 1 if mark_price else 0,
                    "signals_true": len(intents) if mark_price else 0,
                    "signals_false": 1 if mark_price and not intents else 0,
                    "entries_requested": len(intents) if mark_price else 0,
                    "entries_rejected_risk": 0,
                    "entries_rejected_cooldown": 0,
                    "entries_rejected_position_limit": 1 if strategy_rejection_reason == "max_open_levels_reached" else 0,
                    "entries_rejected_session": len(intents) if intents and not entries_enabled else 0,
                    "entries_rejected_duplicate": 0,
                    "entries_rejected_other": 1 if order_rejection_reason else 0,
                    "paper_orders_submitted": intents_applied,
                    "paper_orders_filled": intents_applied,
                    "positions_opened": sum(1 for event in cycle_events if event.get("event") == "position_opened"),
                    "positions_closed": sum(1 for event in cycle_events if event.get("event") == "position_closed"),
                    "last_cycle_at": snapshot["timestamp"],
                    "last_signal_at": _now_iso() if intents else None,
                    "last_order_attempt_at": _now_iso() if intents_applied else None,
                    "last_fill_at": _now_iso() if intents_applied else None,
                    "last_close_at": _now_iso() if closed else None,
                    "rejection_reasons": rejection_reasons,
                }
                postgres.sync_tick(
                    engine.state,
                    snapshot,
                    os.getpid(),
                    execution_events=cycle_events,
                    cycle_started_at=cycle_started_at,
                    market_data_source=price_result.source if mark_price is not None else "unknown",
                    market_data_fresh=mark_price is not None,
                    cycle_diagnostics={
                        "signal_score": None,
                        "entry_threshold": None,
                        "market_data_age": 0.0 if mark_price is not None else None,
                        "volatility": None,
                        "spread": None,
                        "risk_rejection_reason": None,
                        "strategy_rejection_reason": strategy_rejection_reason,
                        "order_rejection_reason": order_rejection_reason,
                        "decision_funnel": funnel,
                    },
                )
                print(json.dumps({
                    "event": "grid_tick",
                    "timestamp": snapshot["timestamp"],
                    "equity": snapshot["current_equity"],
                    "open_positions": len(snapshot["open_positions"]),
                    "occupied_levels": len(strategy.occupied),
                    "intents_applied": intents_applied,
                    "closed_this_tick": len(closed),
                }), flush=True)
            except KeyboardInterrupt:
                break
            except Exception as exc:  # noqa: BLE001
                print(json.dumps({"event": "poll_error", "error": str(exc), "timestamp": _now_iso()}), flush=True)
            remaining = max(1, tick_seconds)
            while remaining > 0:
                sleep_for = min(5, remaining)
                time.sleep(sleep_for)
                remaining -= sleep_for
                try:
                    postgres.heartbeat(os.getpid())
                    _update_heartbeat(session_dir)
                except Exception as exc:  # reconnect on the next heartbeat/tick
                    print(json.dumps({
                        "event": "heartbeat_error", "error": str(exc),
                        "timestamp": _now_iso(),
                    }), flush=True)
    finally:
        postgres.close()
        engine.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a bounded_grid_v1 paper account against live prices")
    parser.add_argument("--session-dir", required=True, type=Path)
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--account-id", required=True, type=UUID)
    parser.add_argument("--strategy-id", required=True)
    parser.add_argument("--timeframe", required=True)
    parser.add_argument("--mode", default="paper", choices=["paper", "live"])
    parser.add_argument("--leverage", required=True, type=int, choices=[5, 10])
    parser.add_argument("--tick-seconds", type=int, default=5)
    args = parser.parse_args()
    identity = WorkerIdentity(
        account_id=args.account_id,
        strategy_id=args.strategy_id,
        worker_id=args.worker_id,
        timeframe=args.timeframe,
        mode=args.mode,
        leverage=args.leverage,
    )
    run(args.session_dir.resolve(), args.tick_seconds, identity)


if __name__ == "__main__":
    main()
