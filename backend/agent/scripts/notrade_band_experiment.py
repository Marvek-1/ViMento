"""Offline no-trade-band experiment over the 3 reconstructed paper sessions.

Answers one question: does suppressing small equal-weight-rebalance trades
(below a minimum weight-delta and/or minimum notional) improve net return,
fee drag, turnover, or drawdown, relative to the strategy as actually run?

This is a pure re-simulation. It never touches paper_sessions/ or
paper_sessions_reconstructed/, never calls the live exchange, and does not
change rebalance_if_due's behavior -- it replays each session's own
historical price series (marks.jsonl's "prices" field, which
session_reconciliation.py already established is trustworthy market data
independent of the cash-ledger bug) through a standalone simulator
parameterized by (min_weight_delta, min_notional), triggering at the same
real recorded mark timestamps rebalance_if_due would have used (rather than
a synthetic checkpoint grid, which only approximates the real polling
cadence and introduces its own small equity drift).

Reuses paper_session.compute_trade_stats / _compute_unrealized_position_pnl
for the realized/unrealized P&L math so the simulator's accounting model is
identical (weighted-average cost, allocated entry fees, oversell clipping)
to the live, tested code -- not a second, independently-verified copy of it.

The key metric is rebalance_value_added = strategy net_return minus the
buy-and-hold return of the same entry basket held untouched -- a threshold
only earns consideration if it improves *that*, not merely if it cuts
trade count, since cutting trades to zero trivially converges to
buy-and-hold and would otherwise look like a free win.
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paper_session as ps

SESSIONS = [
    "demo_10k_8pair_5m_20260710_164304",
    "demo_10k_8pair_10m_20260710_164304",
    "demo_10k_8pair_15m_20260710_164304",
]

MIN_WEIGHT_DELTA_GRID = [
    0.0, 0.00025, 0.00050, 0.00075, 0.00100, 0.00125,
    0.00150, 0.00175, 0.00200, 0.00225, 0.00250,
]
MIN_NOTIONAL_GRID = [0.0, 2.0, 5.0, 7.5, 10.0, 12.5, 15.0, 20.0, 25.0]

BUY_AND_HOLD = (0.0, float("inf"))  # never passes either gate -> zero rebalances, ever


def simulate(
    session_dir: Path,
    min_weight_delta: float,
    min_notional: float,
) -> dict[str, Any]:
    session = ps._load_session(session_dir)
    marks = ps._read_jsonl(session_dir / "marks.jsonl")
    original_trades = ps._read_jsonl(session_dir / "trades.jsonl")
    symbols = session["symbols"]
    fee_rate = session.get("fee_rate", 0.0)
    interval = ps.timedelta(hours=session["rebalance_interval_hours"])
    initial_cash = float(session["initial_cash"])

    # Replay the *actual recorded* entry trades (not a freshly-derived entry
    # sizing formula) so this simulator's baseline starts from the exact
    # same state as the reconstructed session -- the recorded entry already
    # reflects this session's real (pre-fix, per_symbol_cash = initial_cash/n)
    # sizing; recomputing it here would introduce a second, unrelated
    # discrepancy on top of the one this experiment is actually testing.
    entry_trades = [t for t in original_trades if t["reason"] == "entry"]
    positions = {t["symbol"]: t["qty"] for t in entry_trades}
    cash = initial_cash - sum(t["notional"] + t.get("fee_paid", 0.0) for t in entry_trades)
    entry_time = ps._parse_iso(session["entry_time"])
    entry_fees = sum(t.get("fee_paid", 0.0) or 0.0 for t in entry_trades)

    trades: list[dict[str, Any]] = [dict(t) for t in entry_trades]

    last_rebalance_time = entry_time
    equity_curve: list[float] = []
    turnover = sum(t["notional"] for t in entry_trades)
    last_prices = {t["symbol"]: t["price"] for t in entry_trades}
    rebalance_notionals: list[float] = []
    opportunities_evaluated = 0

    peak = None
    max_drawdown = 0.0

    for mark in marks:
        prices = mark.get("prices") or {}
        if not all(code in prices for code in symbols):
            continue
        last_prices = prices
        ts = ps._parse_iso(mark["timestamp"])

        position_values = {code: positions[code] * prices[code] for code in symbols}
        equity = cash + sum(position_values.values())

        if ts - last_rebalance_time >= interval:
            target_value = equity / len(symbols)
            for code in symbols:
                delta_value = target_value - position_values[code]
                if abs(delta_value) < ps.MIN_TRADE_NOTIONAL:
                    continue  # not a real rebalance opportunity at all -- dust, same floor as live code
                opportunities_evaluated += 1
                weight_delta = abs(delta_value) / equity if equity else 0.0
                if weight_delta < min_weight_delta or abs(delta_value) < min_notional:
                    continue
                delta_qty = delta_value / prices[code]
                fee_paid = abs(delta_value) * fee_rate
                trades.append({
                    "timestamp": mark["timestamp"], "symbol": code,
                    "side": "BUY" if delta_qty > 0 else "SELL",
                    "qty": abs(delta_qty), "price": prices[code],
                    "notional": abs(delta_value), "fee_paid": fee_paid, "reason": "rebalance",
                })
                positions[code] += delta_qty
                cash -= delta_value + fee_paid
                turnover += abs(delta_value)
                rebalance_notionals.append(abs(delta_value))
            last_rebalance_time = ts
            position_values = {code: positions[code] * prices[code] for code in symbols}
            equity = cash + sum(position_values.values())

        equity_curve.append(equity)
        peak = equity if peak is None else max(peak, equity)
        drawdown = (equity - peak) / peak if peak else 0.0
        max_drawdown = min(max_drawdown, drawdown)

    trade_stats = ps.compute_trade_stats(trades)
    overall = trade_stats["overall"]
    position = ps._compute_unrealized_position_pnl(trade_stats["by_symbol"], last_prices)

    final_equity = equity_curve[-1] if equity_curve else initial_cash
    realized_pnl = overall["realized_pnl"]
    unrealized_pnl = position["unrealized_pnl"]
    reconciliation_error = (
        final_equity - (initial_cash + realized_pnl + unrealized_pnl)
        if unrealized_pnl is not None else None
    )
    rebalance_trade_count = sum(1 for t in trades if t["reason"] == "rebalance")
    total_fees = overall["fees_paid"]

    return {
        "session_id": session_dir.name,
        "min_weight_delta": min_weight_delta,
        "min_notional": min_notional,
        "trade_count": rebalance_trade_count,
        "opportunities_evaluated": opportunities_evaluated,
        "final_equity": final_equity,
        "net_return": (final_equity - initial_cash) / initial_cash,
        "realized_pnl": realized_pnl,
        "unrealized_pnl": unrealized_pnl,
        "total_fees": total_fees,
        "entry_fees": entry_fees,
        "rebalance_fees": total_fees - entry_fees,
        "turnover": turnover,
        "turnover_multiple": turnover / initial_cash,
        "max_drawdown": max_drawdown,
        "profit_factor": overall["profit_factor"],
        "fee_ratio": (total_fees / (total_fees + max(realized_pnl, 0.0))
                      if (total_fees + max(realized_pnl, 0.0)) else None),
        "avg_trade_notional": statistics.mean(rebalance_notionals) if rebalance_notionals else None,
        "median_trade_notional": statistics.median(rebalance_notionals) if rebalance_notionals else None,
        "reconciliation_error": reconciliation_error,
    }


def run_grid(sessions_dir: Path, session_ids: list[str] = SESSIONS) -> list[dict[str, Any]]:
    results = []
    for session_id in session_ids:
        session_dir = sessions_dir / session_id
        for mwd in MIN_WEIGHT_DELTA_GRID:
            for mn in MIN_NOTIONAL_GRID:
                results.append(simulate(session_dir, mwd, mn))
        results.append(simulate(session_dir, *BUY_AND_HOLD))
    return results


def annotate_with_baselines(results: list[dict[str, Any]], session_ids: list[str] = SESSIONS) -> None:
    """In place: add buy_and_hold_net_return, rebalance_value_added,
    incremental_vs_unrestricted_baseline, and pct_rebalances_suppressed."""
    buy_hold_return: dict[str, float] = {}
    unrestricted_return: dict[str, float] = {}
    unrestricted_trade_count: dict[str, int] = {}
    for r in results:
        if (r["min_weight_delta"], r["min_notional"]) == BUY_AND_HOLD:
            buy_hold_return[r["session_id"]] = r["net_return"]
        if r["min_weight_delta"] == 0.0 and r["min_notional"] == 0.0:
            unrestricted_return[r["session_id"]] = r["net_return"]
            unrestricted_trade_count[r["session_id"]] = r["trade_count"]

    for r in results:
        sid = r["session_id"]
        r["buy_and_hold_net_return"] = buy_hold_return.get(sid)
        r["rebalance_value_added"] = (
            r["net_return"] - buy_hold_return[sid] if sid in buy_hold_return else None
        )
        r["incremental_vs_unrestricted_baseline"] = (
            r["net_return"] - unrestricted_return[sid] if sid in unrestricted_return else None
        )
        baseline_trades = unrestricted_trade_count.get(sid, 0)
        r["pct_rebalances_suppressed"] = (
            1.0 - r["trade_count"] / baseline_trades if baseline_trades else None
        )


def leave_one_out_best(
    results: list[dict[str, Any]], session_ids: list[str] = SESSIONS,
) -> list[dict[str, Any]]:
    """For each held-out session, pick the (min_weight_delta, min_notional)
    that maximizes the WORST rebalance_value_added across the other two
    sessions (train), then report that threshold's performance on the
    held-out one (test)."""
    by_key: dict[tuple[float, float], dict[str, dict[str, Any]]] = {}
    for r in results:
        key = (r["min_weight_delta"], r["min_notional"])
        by_key.setdefault(key, {})[r["session_id"]] = r

    report = []
    for held_out in session_ids:
        train_ids = [s for s in session_ids if s != held_out]
        best_key = None
        best_worst_value_added = float("-inf")
        for key, per_session in by_key.items():
            if key == BUY_AND_HOLD or not all(sid in per_session for sid in train_ids):
                continue
            worst_value_added = min(per_session[sid]["rebalance_value_added"] for sid in train_ids)
            if worst_value_added > best_worst_value_added:
                best_worst_value_added = worst_value_added
                best_key = key
        if best_key is None:
            continue
        test_result = by_key[best_key].get(held_out)
        report.append({
            "held_out_session": held_out,
            "chosen_min_weight_delta": best_key[0],
            "chosen_min_notional": best_key[1],
            "train_worst_rebalance_value_added": best_worst_value_added,
            "test_rebalance_value_added": test_result["rebalance_value_added"] if test_result else None,
            "test_net_return": test_result["net_return"] if test_result else None,
            "test_trade_count": test_result["trade_count"] if test_result else None,
            "test_pct_suppressed": test_result["pct_rebalances_suppressed"] if test_result else None,
            "test_rebalance_fees": test_result["rebalance_fees"] if test_result else None,
            "test_max_drawdown": test_result["max_drawdown"] if test_result else None,
        })
    return report


def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions-dir", default=str(ps.SESSIONS_DIR))
    parser.add_argument("--csv-out", default=None)
    args = parser.parse_args()

    results = run_grid(Path(args.sessions_dir))
    annotate_with_baselines(results)
    if args.csv_out:
        with open(args.csv_out, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(results[0].keys()))
            writer.writeheader()
            writer.writerows(results)

    print(json.dumps({
        "grid_results": results,
        "leave_one_session_out": leave_one_out_best(results),
    }, indent=2))


if __name__ == "__main__":
    _cli()
