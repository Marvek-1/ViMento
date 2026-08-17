from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# The paper-trading engine lives one directory up, in backend/agent/. This
# script used to sit next to its own copy of paper_session.py (removed --
# see archive/retired-paper-engine/); inserting the canonical directory here
# ensures `from paper_session import ...` always resolves to the one
# implementation the live API also imports, not a stale sibling.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from paper_session import run_paired_loop, start_paired_sessions


def ensure_paired_sessions(
    control_dir: Path,
    candidate_dir: Path,
    symbols: list[str],
    initial_cash: float,
    rebalance_interval_hours: float,
    fee_rate: float,
    candidate_min_notional: float,
    leverage: float = 1.0,
    portfolio_leverage: bool = False,
) -> list[dict[str, Any]]:
    exists = (control_dir.exists(), candidate_dir.exists())
    if exists[0] != exists[1]:
        raise RuntimeError("paired sessions must either both exist or both be absent")

    if not any(exists):
        return start_paired_sessions(
            [
                {
                    "session_dir": control_dir,
                    "symbols": symbols,
                    "initial_cash": initial_cash,
                    "rebalance_interval_hours": rebalance_interval_hours,
                    "fee_rate": fee_rate,
                    "min_rebalance_notional": 0.0,
                    "risk_config": {"leverage": leverage, "portfolio_leverage": portfolio_leverage,
                                    "margin_mode": "isolated", "liquidation_buffer_pct": 0.005},
                },
                {
                    "session_dir": candidate_dir,
                    "symbols": symbols,
                    "initial_cash": initial_cash,
                    "rebalance_interval_hours": rebalance_interval_hours,
                    "fee_rate": fee_rate,
                    "min_rebalance_notional": candidate_min_notional,
                    "risk_config": {"leverage": leverage, "portfolio_leverage": portfolio_leverage,
                                    "margin_mode": "isolated", "liquidation_buffer_pct": 0.005},
                },
            ]
        )

    sessions = [
        json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
        for session_dir in (control_dir, candidate_dir)
    ]
    if sessions[0]["entry_time"] != sessions[1]["entry_time"]:
        raise RuntimeError("existing pair has different entry timestamps")
    if sessions[0]["entry_prices"] != sessions[1]["entry_prices"]:
        raise RuntimeError("existing pair has different entry prices")
    if set(sessions[0]["symbols"]) != set(sessions[1]["symbols"]):
        raise RuntimeError("existing pair has different symbol sets")
    if any(set(session["symbols"]) != set(symbols) for session in sessions):
        raise RuntimeError("existing pair does not match requested symbols")
    if any(float(session["initial_cash"]) != initial_cash for session in sessions):
        raise RuntimeError("existing pair does not match requested cash")
    if any(float(session["rebalance_interval_hours"]) != rebalance_interval_hours for session in sessions):
        raise RuntimeError("existing pair does not match requested interval")
    if any(float(session["fee_rate"]) != fee_rate for session in sessions):
        raise RuntimeError("existing pair does not match requested fee rate")
    if float(sessions[0]["min_rebalance_notional"]) != 0.0:
        raise RuntimeError("existing control is not the zero-band policy")
    if float(sessions[1]["min_rebalance_notional"]) != candidate_min_notional:
        raise RuntimeError("existing candidate does not match requested no-trade band")
    if any(bool(s.get("risk_config", {}).get("portfolio_leverage", False)) != portfolio_leverage for s in sessions):
        raise RuntimeError("existing pair does not match requested portfolio leverage mode")
    if portfolio_leverage and any(float(s.get("risk_config", {}).get("leverage", 1.0)) != leverage for s in sessions):
        raise RuntimeError("existing pair does not match requested leverage")
    return sessions


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--control-dir", type=Path, required=True)
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--symbols", required=True)
    parser.add_argument("--cash", type=float, required=True)
    parser.add_argument("--rebalance-hours", type=float, required=True)
    parser.add_argument("--fee-rate", type=float, required=True)
    parser.add_argument("--candidate-min-notional", type=float, required=True)
    parser.add_argument("--leverage", type=float, choices=[1.0, 5.0, 10.0], default=1.0)
    parser.add_argument("--portfolio-leverage", action="store_true")
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument("--until")
    args = parser.parse_args()

    symbols = [symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()]
    ensure_paired_sessions(
        args.control_dir,
        args.candidate_dir,
        symbols,
        args.cash,
        args.rebalance_hours,
        args.fee_rate,
        args.candidate_min_notional,
        args.leverage,
        args.portfolio_leverage,
    )
    run_paired_loop([args.control_dir, args.candidate_dir], args.poll_seconds, args.until)


if __name__ == "__main__":
    main()
