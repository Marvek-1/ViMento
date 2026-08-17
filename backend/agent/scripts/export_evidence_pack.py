#!/usr/bin/env python3
"""VT edge-extraction evidence pack.

Read-only. For each session with positive dashboard P&L, exports:
  session_config.json, closed_trades.csv, raw_fills.csv,
  open_positions.json, equity_reconstruction.csv, attribution.json,
  reproduction.json

into --out-dir/<session_id>/. No session state is mutated.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_DIR))

import paper_session as ps  # noqa: E402

PAPER_SESSIONS_DIR = AGENT_DIR / "paper_sessions"


def _parse_iso(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def build_session_config(session_dir: Path, session: dict, trades: list[dict], marks: list[dict]) -> dict:
    risk = session.get("risk_config", {})
    start_ts = session.get("entry_time")
    end_ts = marks[-1]["timestamp"] if marks else None
    return {
        "session_id": session_dir.name,
        "start_timestamp": start_ts,
        "end_timestamp_of_export": end_ts,
        "status_at_export": "open_ended (still running)",
        "starting_capital": session.get("initial_cash"),
        "strategy_id": session.get("strategy_type"),
        "accounting_schema_version": session.get("accounting_schema_version"),
        "entry_exit_rules": {
            "entry_z": session.get("entry_z"),
            "exit_z": session.get("exit_z"),
            "z_window": session.get("z_window"),
            "rebalance_interval_hours": session.get("rebalance_interval_hours"),
            "min_rebalance_notional": session.get("min_rebalance_notional"),
            "max_position_pct": session.get("max_position_pct"),
            "description": (
                "funding_rate_zscore: open when funding-rate z-score crosses "
                "+/-entry_z (long when z<=-entry_z, short when z>=+entry_z), "
                "exit when |z| crosses back below exit_z"
                if session.get("strategy_type") == "funding_rate_zscore"
                else "periodic_equal_weight_rebalance: enter equal-weight across "
                "the symbol universe at session start, then on a fixed interval "
                "sell what's drifted above equal-weight share and buy what's "
                "drifted below, snapping back to equal weight"
            ),
        },
        "universe": session.get("symbols"),
        "direction_rules": "long+short (funding z-score sign)" if session.get("strategy_type") == "funding_rate_zscore" else "long-only (spot rebalance)",
        "leverage": risk.get("leverage"),
        "margin_mode": risk.get("margin_mode"),
        "position_sizing": {
            "fixed_margin_per_trade": risk.get("fixed_margin_per_trade"),
            "max_position_pct": session.get("max_position_pct"),
            "max_concurrent_positions": len(session.get("symbols", [])),
        },
        "risk_controls": {
            "take_profit_pct": risk.get("take_profit_pct"),
            "stop_loss_pct": risk.get("stop_loss_pct"),
            "trailing_stop_pct": risk.get("trailing_stop_pct"),
            "max_hold_hours": risk.get("max_hold_hours"),
            "liquidation_buffer_pct": risk.get("liquidation_buffer_pct"),
        },
        "cost_models": {
            "fee_rate": session.get("fee_rate"),
            "fees_modeled": session.get("fees_modeled"),
            "slippage_rate": session.get("slippage_rate"),
            "slippage_modeled": session.get("slippage_modeled"),
            "spread_modeled": False,
            "funding_modeled": False,  # confirmed by audit: funding_rate recorded as signal input only, never settled
            "liquidation_modeled": "liquidation_price computed; forced-liquidation execution path untested in this session's history",
        },
        "price_source": session.get("source"),
    }


def build_journal(trades: list[dict]) -> tuple[list[dict], list[dict]]:
    """Returns (raw_fills_annotated, closed_only) via paper_session's own
    signed-cost-basis reconstruction -- the authoritative entry/exit pairing.
    """
    stats = ps.compute_trade_stats(trades)
    annotated = stats["trades"]
    closed = [t for t in annotated if t.get("net_pnl") is not None]
    return annotated, closed


def build_open_positions(book: dict | None, latest_mark: dict | None, initial_cash: float) -> dict:
    if book is None:
        return {"positions": [], "realized_pnl_to_date": None, "unrealized_pnl": None, "reserved_margin": None, "available_balance": None}
    meta = book.get("position_metadata", {})
    positions = []
    unrealized_total = 0.0
    if latest_mark:
        pnl_map = latest_mark.get("position_pnl", {})
        price_map = latest_mark.get("prices", {})
        val_map = latest_mark.get("position_values", {})
    else:
        pnl_map = price_map = val_map = {}
    for sym, qty in book.get("positions", {}).items():
        if abs(qty) < 1e-9:
            continue
        m = meta.get(sym, {})
        upnl = pnl_map.get(sym, 0.0)
        unrealized_total += upnl or 0.0
        positions.append({
            "symbol": sym,
            "qty": qty,
            "direction": m.get("direction"),
            "entry_price": m.get("entry_price"),
            "mark_price": price_map.get(sym),
            "notional_value": val_map.get(sym),
            "leverage": m.get("leverage"),
            "margin": m.get("margin"),
            "margin_mode": m.get("margin_mode"),
            "liquidation_price": m.get("liquidation_price"),
            "entry_time": m.get("entry_time"),
            "unrealized_pnl": upnl,
        })
    equity = latest_mark.get("equity") if latest_mark else None
    realized_to_date = (equity - initial_cash - unrealized_total) if equity is not None else None
    return {
        "positions": positions,
        "realized_pnl_to_date_derived": realized_to_date,
        "unrealized_pnl_total": unrealized_total,
        "reserved_margin": book.get("reserved_margin"),
        "cash_remaining": book.get("cash_remaining"),
        "note": "realized_pnl_to_date_derived = equity - initial_cash - unrealized_pnl_total; cross-check against closed_trades.csv net_pnl sum for the conservation audit",
    }


def build_equity_reconstruction(trades: list[dict], marks: list[dict], initial_cash: float) -> list[dict]:
    """Event-by-event: for each trade, the naive full-notional cash model's
    expected running cash vs. the actual cash_remaining at the next mark at
    or after that trade -- the same methodology that surfaced the
    trailing_stop / max_hold_expired settlement bug in funding_live.
    """
    mark_times = [(_parse_iso(m["timestamp"]), m) for m in marks]
    rows = []
    expected_cash = initial_cash
    for i, t in enumerate(trades):
        notional = t.get("notional", 0.0)
        fee = t.get("fee_paid", 0.0) or 0.0
        if t["side"] == "BUY":
            expected_cash -= (notional + fee)
        else:
            expected_cash += (notional - fee)
        target = _parse_iso(t["timestamp"])
        actual_cash = None
        actual_ts = None
        for mt, m in mark_times:
            if mt >= target:
                actual_cash = m.get("cash_remaining")
                actual_ts = m["timestamp"]
                break
        residual = None if actual_cash is None else actual_cash - expected_cash
        rows.append({
            "event_index": i,
            "trade_timestamp": t["timestamp"],
            "symbol": t["symbol"],
            "side": t["side"],
            "reason": t.get("reason"),
            "notional": notional,
            "fee_paid": fee,
            "expected_cash_after_naive_full_notional_model": round(expected_cash, 8),
            "actual_cash_at_next_mark": actual_cash,
            "actual_mark_timestamp": actual_ts,
            "conservation_residual": None if residual is None else round(residual, 8),
        })
    return rows


def _hold_bucket(hold_seconds: float | None) -> str:
    if hold_seconds is None:
        return "unknown"
    h = hold_seconds / 3600.0
    if h < 1:
        return "<1h"
    if h < 6:
        return "1-6h"
    if h < 24:
        return "6-24h"
    return ">24h"


def build_attribution(closed: list[dict], marks: list[dict], symbols: list[str]) -> dict:
    by_symbol: dict[str, float] = {}
    by_side: dict[str, float] = {"long_close": 0.0, "short_close": 0.0}
    by_bucket: dict[str, float] = {}
    total_net = 0.0
    for t in closed:
        net = t["net_pnl"]
        total_net += net
        by_symbol[t["symbol"]] = by_symbol.get(t["symbol"], 0.0) + net
        was_long_close = t.get("position_before", 0) > 0
        by_side["long_close" if was_long_close else "short_close"] += net
        entry_t = t.get("entry_time")
        hold_s = None
        if entry_t:
            try:
                hold_s = (_parse_iso(t["timestamp"]) - _parse_iso(entry_t)).total_seconds()
            except Exception:
                hold_s = None
        bucket = _hold_bucket(hold_s)
        by_bucket[bucket] = by_bucket.get(bucket, 0.0) + net

    benchmark = None
    if marks and symbols:
        first_prices = marks[0].get("prices", {})
        last_prices = marks[-1].get("prices", {})
        rets = []
        for sym in symbols:
            p0 = first_prices.get(sym)
            p1 = last_prices.get(sym)
            if p0 and p1:
                rets.append((p1 - p0) / p0)
        if rets:
            benchmark = {
                "method": "equal_weight_buy_and_hold, session first mark to last mark",
                "window_start": marks[0]["timestamp"],
                "window_end": marks[-1]["timestamp"],
                "mean_symbol_return_pct": round(sum(rets) / len(rets) * 100, 4),
                "symbols_used": len(rets),
                "per_symbol_return_pct": {
                    sym: round((last_prices[sym] - first_prices[sym]) / first_prices[sym] * 100, 4)
                    for sym in symbols
                    if first_prices.get(sym) and last_prices.get(sym)
                },
            }

    return {
        "total_realized_net_pnl_from_closed_trades": round(total_net, 8),
        "by_symbol": {k: round(v, 8) for k, v in by_symbol.items()},
        "by_side": {k: round(v, 8) for k, v in by_side.items()},
        "by_holding_time_bucket": {k: round(v, 8) for k, v in by_bucket.items()},
        "benchmark_equal_weight_buy_and_hold": benchmark,
        "single_direction_market_move_flag": (
            "CHECK: compare total_realized_net_pnl_from_closed_trades against "
            "benchmark_equal_weight_buy_and_hold.mean_symbol_return_pct applied to "
            "starting_capital -- if of similar sign/magnitude, positive dashboard "
            "P&L may just be tracking a broad market move rather than strategy edge"
        ),
    }


def build_reproduction(session_dir: Path, session: dict) -> dict:
    strategy = session.get("strategy_type")
    cmd = "run-funding" if strategy == "funding_rate_zscore" else "run"
    return {
        "warning": (
            "paper_session.py fetches LIVE prices from Binance/OKX at poll time -- "
            "there is no deterministic historical-replay mode in this codebase. "
            "The command below reproduces the LIVE PROCESS that generated this "
            "session, not a byte-identical replay from the original raw ticks. "
            "marks.jsonl in this session directory is the only raw-price snapshot "
            "record available; exact reproduction requires replaying trades.jsonl "
            "price/qty values through a ledger (e.g. accounting/futures_ledger.py), "
            "not re-running this command against today's live market."
        ),
        "live_process_command": (
            f"cd backend/agent && ../../.venv/bin/python paper_session.py {cmd} "
            f"--session-dir paper_sessions/{session_dir.name} --poll-seconds 60"
        ),
        "api_reproduction": f"GET /paper-sessions/{session_dir.name}  (requires API_AUTH_KEY if set)",
        "deterministic_journal_replay_status": "not implemented -- see accounting/futures_ledger.py replay TODO",
    }


def export_session(session_id: str, out_dir: Path) -> dict:
    session_dir = PAPER_SESSIONS_DIR / session_id
    session = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
    book_path = session_dir / "book.json"
    book = json.loads(book_path.read_text(encoding="utf-8")) if book_path.exists() else None
    trades = _read_jsonl(session_dir / "trades.jsonl")
    marks = _read_jsonl(session_dir / "marks.jsonl")
    latest_mark = marks[-1] if marks else None
    initial_cash = float(session.get("initial_cash", 0.0))

    sdir = out_dir / session_id
    sdir.mkdir(parents=True, exist_ok=True)

    config = build_session_config(session_dir, session, trades, marks)
    (sdir / "session_config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")

    annotated, closed = build_journal(trades)
    fills_fields = sorted({k for row in annotated for k in row.keys()})
    with (sdir / "raw_fills.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fills_fields)
        w.writeheader()
        w.writerows(annotated)
    closed_fields = sorted({k for row in closed for k in row.keys()})
    with (sdir / "closed_trades.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=closed_fields)
        w.writeheader()
        w.writerows(closed)

    open_pos = build_open_positions(book, latest_mark, initial_cash)
    (sdir / "open_positions.json").write_text(json.dumps(open_pos, indent=2), encoding="utf-8")

    equity_rows = build_equity_reconstruction(trades, marks, initial_cash)
    if equity_rows:
        with (sdir / "equity_reconstruction.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(equity_rows[0].keys()))
            w.writeheader()
            w.writerows(equity_rows)

    attribution = build_attribution(closed, marks, session.get("symbols", []))
    (sdir / "attribution.json").write_text(json.dumps(attribution, indent=2), encoding="utf-8")

    reproduction = build_reproduction(session_dir, session)
    (sdir / "reproduction.json").write_text(json.dumps(reproduction, indent=2), encoding="utf-8")

    summary = {
        "session_id": session_id,
        "closed_trade_count": len(closed),
        "total_realized_net_pnl": attribution["total_realized_net_pnl_from_closed_trades"],
        "current_equity": latest_mark.get("equity") if latest_mark else None,
        "dashboard_pnl": (latest_mark.get("equity") - initial_cash) if latest_mark else None,
        "max_conservation_residual_abs": max(
            (abs(r["conservation_residual"]) for r in equity_rows if r["conservation_residual"] is not None),
            default=0.0,
        ),
    }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessions", nargs="+", required=True)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()

    summaries = []
    for sid in args.sessions:
        summaries.append(export_session(sid, args.out_dir))

    index_path = args.out_dir / "_index.json"
    index_path.write_text(json.dumps(summaries, indent=2), encoding="utf-8")
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    main()
