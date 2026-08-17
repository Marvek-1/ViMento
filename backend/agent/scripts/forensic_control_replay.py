#!/usr/bin/env python3
"""Locate the first inventory divergence in an immutable paper session.

The live session is never modified. Historical engine quantities are derived
from each mark's receipted position value and price, then compared with a
prefix replay of trades.jsonl. The report is written to a separate replay
candidate directory suitable for release evidence.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from paper_session import compute_trade_stats


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            row = json.loads(line)
            row["_line_number"] = line_number
            rows.append(row)
    return rows


def mark_positions(mark: dict[str, Any]) -> dict[str, float]:
    result: dict[str, float] = {}
    prices = mark.get("prices", {})
    for symbol, value in mark.get("position_values", {}).items():
        price = float(prices.get(symbol, 0.0) or 0.0)
        if price > 0:
            result[symbol] = float(value) / price
    return result


def classify(position_delta: float, equity_delta: float, fees: float, funding: float, tolerance: float) -> str:
    if abs(position_delta) > tolerance:
        return "POSITION_EVENT_MISMATCH"
    if abs(equity_delta - funding) <= tolerance:
        return "FUNDING_APPLICATION_MISMATCH"
    if abs(equity_delta - fees) <= tolerance or abs(equity_delta + fees) <= tolerance:
        return "FEE_SIGN_OR_DUPLICATION"
    if abs(equity_delta) <= tolerance:
        return "ROUNDING_ONLY"
    return "UNCLASSIFIED_LEDGER_DRIFT"


def analyze(source: Path, tolerance: float) -> dict[str, Any]:
    session = json.loads((source / "session.json").read_text(encoding="utf-8"))
    trades = read_jsonl(source / "trades.jsonl")
    marks = read_jsonl(source / "marks.jsonl")
    first: dict[str, Any] | None = None

    for mark_index, mark in enumerate(marks):
        timestamp = str(mark["timestamp"])
        prefix = [trade for trade in trades if str(trade["timestamp"]) <= timestamp]
        stats = compute_trade_stats(prefix)
        engine_positions = mark_positions(mark)
        symbols = sorted(set(engine_positions) | set(stats["by_symbol"]))
        for symbol in symbols:
            ledger_qty = float(stats["by_symbol"].get(symbol, {}).get("open_qty", 0.0) or 0.0)
            engine_qty = float(engine_positions.get(symbol, 0.0) or 0.0)
            qty_delta = ledger_qty - engine_qty
            qty_limit = max(tolerance, tolerance * max(abs(ledger_qty), abs(engine_qty), 1.0))
            if not math.isclose(ledger_qty, engine_qty, abs_tol=tolerance, rel_tol=tolerance):
                last_trade = prefix[-1] if prefix else None
                fees = float(stats["overall"].get("fees_paid", 0.0) or 0.0)
                realized = float(stats["overall"].get("realized_pnl", 0.0) or 0.0)
                initial = float(session["initial_cash"])
                equity = float(mark["equity"])
                cash = float(mark["cash_remaining"])
                market_value = sum(float(v) for v in mark.get("position_values", {}).values())
                cash_identity_delta = equity - (cash + market_value)
                first = {
                    "worker_id": session.get("worker_id", source.name),
                    "account_id": session.get("account_id"),
                    "strategy_id": session.get("strategy_id", "control"),
                    "timeframe": session.get("timeframe"),
                    "mark_index": mark_index,
                    "mark_line_number": mark.get("_line_number"),
                    "timestamp": timestamp,
                    "symbol": symbol,
                    "ledger_qty": ledger_qty,
                    "engine_qty": engine_qty,
                    "position_delta": qty_delta,
                    "ledger_cash": None,
                    "engine_cash": cash,
                    "ledger_equity": initial + realized,
                    "engine_equity": equity,
                    "realized_pnl": realized,
                    "unrealized_pnl": None,
                    "fees": fees,
                    "funding": 0.0,
                    "position_cost_basis": float(stats["by_symbol"].get(symbol, {}).get("open_cost_basis", 0.0) or 0.0),
                    "position_market_value": market_value,
                    "cash_plus_market_value_delta": cash_identity_delta,
                    "last_ledger_event_id": None,
                    "last_fill_id": (last_trade or {}).get("fill_id"),
                    "last_trade_line_number": (last_trade or {}).get("_line_number"),
                    "last_trade": last_trade,
                    "difference": equity - (initial + realized),
                    "cause": classify(qty_delta, equity - (initial + realized), fees, 0.0, qty_limit),
                }
                break
        if first is not None:
            break

    return {
        "source_session": str(source.resolve()),
        "immutable_inputs": ["session.json", "trades.jsonl", "marks.jsonl"],
        "trade_count": len(trades),
        "mark_count": len(marks),
        "first_divergence": first,
        "reconciled_through_all_marks": first is None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tolerance", type=float, default=1e-9)
    args = parser.parse_args()

    if args.output.resolve() == args.source.resolve():
        raise SystemExit("output must be separate from the live source session")
    args.output.mkdir(parents=True, exist_ok=True)
    report = analyze(args.source, args.tolerance)
    for name in ("session.json", "trades.jsonl", "marks.jsonl"):
        source_file = args.source / name
        if source_file.exists():
            shutil.copy2(source_file, args.output / f"immutable_{name}")
    (args.output / "forensic_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
