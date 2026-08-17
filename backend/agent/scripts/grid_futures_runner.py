#!/usr/bin/env python3
"""Poll loop that drives a grid_futures paper account.

grid_futures_10x_v2 and grid_futures_5x_v2 were created as bare
FuturesPaperEngine accounts (session_config.json) with no strategy ever
wired to them -- no positions opened, no runner started. This ties the
existing FrozenMomentumSignal + ManyBotsFuturesAdapter (see
many_bots_futures_adapter.py) to a live price poll, reusing the same
Binance-primary/OKX-fallback price source paper_session.py uses for the
periodic_equal_weight_rebalance sessions, so the account actually trades
and marks.jsonl stops going stale.
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

from futures_paper_engine import (  # noqa: E402
    FuturesPaperEngine,
    RiskConfig,
    normalize_symbol,
    fetch_funding_rate,
    funding_event_id,
    read_jsonl,
)
from many_bots_futures_adapter import ManyBotsFuturesAdapter  # noqa: E402
from paper_postgres import PaperPostgres, WorkerIdentity  # noqa: E402
from paper_session import _update_heartbeat, fetch_last_prices_with_source  # noqa: E402
from timeframe_policy import policy_for  # noqa: E402


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bootstrap_enabled() -> bool:
    return os.getenv("PAPER_BOOTSTRAP_TRADE_ENABLED", "false").lower() == "true"


def _run_bootstrap_trade(engine: FuturesPaperEngine, prices: dict[str, float], identity: WorkerIdentity) -> bool:
    """Run exactly one paper-only lifecycle through the real engine.

    The engine's immutable events are the source for orders, fills, fees and
    the PostgreSQL projection.  This function never writes database rows.
    """
    if not _bootstrap_enabled() or identity.mode != "paper":
        return False
    if engine.state.opened_trades or engine.state.closed_trades or engine.state.positions:
        return False
    symbol = os.getenv("PAPER_BOOTSTRAP_SYMBOL", "BTC-USDT-SWAP")
    # The price map is normalized by the engine (BTC-USDT-SWAP -> BTC-USDT).
    price = prices.get(symbol) or prices.get(symbol.replace("-SWAP", ""))
    if price is None or price <= 0:
        return False
    notional = float(os.getenv("PAPER_BOOTSTRAP_NOTIONAL", "25"))
    if notional <= 0:
        raise ValueError("PAPER_BOOTSTRAP_NOTIONAL must be positive")
    risk = RiskConfig(leverage=identity.leverage, margin=notional / identity.leverage)
    position = engine.open_position(
        symbol, "long", price=price, risk=risk,
        signal_reason="paper_bootstrap_pipeline_validation", market_regime="bootstrap",
    )
    # A tiny deterministic adverse move ensures a non-zero realized result and
    # still uses the engine's genuine closing, fee, and ledger path.
    engine.close_position(
        position.trade_id, price=price * 0.9999,
        exit_reason="paper_bootstrap_validation", order_type="taker",
    )
    return True


def run(session_dir: Path, poll_seconds: int, identity: WorkerIdentity) -> None:
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
    universe_path = (session_dir / config["universe_path"]).resolve()
    if int(config["leverage"]) != identity.leverage:
        raise RuntimeError("session leverage does not match worker/database identity")
    policy = policy_for(identity.timeframe)
    if poll_seconds != policy.decision_interval_seconds:
        raise RuntimeError("decision cadence mismatch")

    engine = FuturesPaperEngine(session_dir, initial_balance=config["initial_balance"])
    postgres = PaperPostgres(identity)
    adapter = ManyBotsFuturesAdapter(
        engine,
        account_id=str(identity.account_id),
        universe_path=universe_path,
        leverage=config["leverage"],
        margin=config["margin_per_trade"],
    )

    last_funding_window: str | None = None
    try:
        while True:
            _update_heartbeat(session_dir)
            try:
                cycle_started_at = datetime.now(timezone.utc)
                price_result = fetch_last_prices_with_source(adapter.universe)
                prices = price_result.prices
                event_count_before = len(read_jsonl(engine.events_path))
                normalized_prices = {normalize_symbol(symbol): float(price) for symbol, price in prices.items()}
                for trade_id, position in list(engine.state.positions.items()):
                    entered = datetime.fromisoformat(position.entry_time)
                    if (cycle_started_at - entered).total_seconds() >= policy.maximum_position_age_seconds:
                        mark_price = normalized_prices.get(normalize_symbol(position.symbol))
                        if mark_price is None:
                            print(json.dumps({"event": "expiry_price_missing", "symbol": position.symbol,
                                              "available_symbols": sorted(normalized_prices)}), flush=True)
                            continue
                        engine.close_position(trade_id, price=mark_price, exit_reason="TIMEFRAME_POLICY_MIGRATION", order_type="taker")
                bootstrap_completed = _run_bootstrap_trade(engine, prices, identity)
                intents = adapter.evaluate_price_tick(prices, timestamp=_now_iso())
                entries_enabled = os.getenv("NEW_ENTRIES_ENABLED", "false").lower() == "true"
                if entries_enabled:
                    applied = adapter.apply_intents(intents, prices)
                else:
                    applied = []
                    diagnostics = adapter.last_diagnostics
                    diagnostics["entries_rejected_session"] = len(intents)
                    diagnostics["rejection_reasons"] = (
                        {"entry_gate_disabled": len(intents)} if intents else {}
                    )
                funding_events: list[dict[str, object]] = []
                now = datetime.now(timezone.utc)
                if now.hour in (0, 8, 16):
                    window = now.strftime("%Y-%m-%dT%H:00:00Z")
                    if window != last_funding_window:
                        for trade_id, position in list(engine.state.positions.items()):
                            try:
                                rate = fetch_funding_rate(
                                    position.symbol,
                                    source=price_result.source,
                                )
                                payment = engine.apply_funding(
                                    trade_id,
                                    rate,
                                    event_id=funding_event_id(position.symbol, window),
                                )
                                funding_events.append({
                                    "symbol": position.symbol,
                                    "funding_timestamp": window,
                                    "funding_rate": rate,
                                    "funding_pnl": -payment,
                                })
                            except Exception as exc:  # funding outage must not stop marks/exits
                                print(json.dumps({
                                    "event": "funding_fetch_error",
                                    "symbol": position.symbol,
                                    "window": window,
                                    "error": str(exc),
                                }), flush=True)
                        last_funding_window = window
                closed = engine.process_all(
                    prices,
                    market_data_source=price_result.source,
                    market_data_observed_at=_now_iso(),
                )
                snapshot = engine.account_summary(prices)
                cycle_events = read_jsonl(engine.events_path)[event_count_before:]
                funnel = dict(adapter.last_diagnostics)
                funnel.update({
                    "cycles_started": 1,
                    "cycles_completed": 1,
                    "positions_opened": sum(1 for event in cycle_events if event.get("event") == "position_opened"),
                    "positions_closed": sum(1 for event in cycle_events if event.get("event") == "position_closed"),
                    "last_cycle_at": snapshot["timestamp"],
                    "last_signal_at": _now_iso() if intents else None,
                    "last_order_attempt_at": _now_iso() if applied else None,
                    "last_fill_at": _now_iso() if applied else None,
                    "last_close_at": _now_iso() if closed else None,
                })
                postgres.sync_tick(
                    engine.state,
                    snapshot,
                    os.getpid(),
                    funding_events=funding_events,
                    execution_events=cycle_events,
                    cycle_started_at=cycle_started_at,
                    market_data_source=price_result.source,
                    # The boolean means this poll produced a usable live quote;
                    # market_data_source is which exchange actually answered.
                    market_data_fresh=bool(prices),
                    cycle_diagnostics={
                        "signal_score": None,
                        "entry_threshold": None,
                        "market_data_age": 0.0 if prices else None,
                        "volatility": None,
                        "spread": None,
                        "risk_rejection_reason": None,
                        "strategy_rejection_reason": (
                            None if applied or bootstrap_completed
                            else "entry_gate_disabled" if intents and not entries_enabled
                            else "no_actionable_signal"
                        ),
                        "order_rejection_reason": None,
                        "decision_funnel": funnel,
                    },
                )
                print(json.dumps({
                    "event": "tick",
                    "timestamp": snapshot["timestamp"],
                    "equity": snapshot["current_equity"],
                    "open_positions": len(snapshot["open_positions"]),
                    "intents_applied": len(applied),
                    "closed_this_tick": len(closed),
                    "bootstrap_completed": bootstrap_completed,
                }), flush=True)
            except KeyboardInterrupt:
                break
            except Exception as exc:  # noqa: BLE001
                print(json.dumps({"event": "poll_error", "error": str(exc), "timestamp": _now_iso()}), flush=True)
            remaining = max(1, poll_seconds)
            while remaining > 0:
                sleep_for = min(15, remaining)
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
    parser = argparse.ArgumentParser(description="Run a grid_futures paper account against live prices")
    parser.add_argument("--session-dir", required=True, type=Path)
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--account-id", required=True, type=UUID)
    parser.add_argument("--strategy-id", required=True)
    parser.add_argument("--timeframe", required=True, choices=["5m", "10m", "15m"])
    parser.add_argument("--mode", default="paper", choices=["paper", "live"])
    parser.add_argument("--leverage", required=True, type=int, choices=[5, 10])
    parser.add_argument("--poll-seconds", type=int, default=60)
    args = parser.parse_args()
    identity = WorkerIdentity(
        account_id=args.account_id,
        strategy_id=args.strategy_id,
        worker_id=args.worker_id,
        timeframe=args.timeframe,
        mode=args.mode,
        leverage=args.leverage,
    )
    run(args.session_dir.resolve(), args.poll_seconds, identity)


if __name__ == "__main__":
    main()
