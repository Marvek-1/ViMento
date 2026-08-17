#!/usr/bin/env python3
"""Physical paper-trading dashboard API for the real shadow session.

Reads/writes the same files as paper_session.py and fetches live Binance
prices. Serves the Snapshot shape expected by PaperTradingDashboard.tsx.
"""
from __future__ import annotations

import argparse
import json
import math
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, parse_qs

from futures_paper_engine import request_json, normalize_symbol
from write_receipt import receipted_write

MARGIN_PER_POSITION = 100.0  # user wants $100 reserved per open trade

PORTFOLIO_CACHE: dict[str, Any] = {}
PORTFOLIO_CACHE_TTL = 5.0  # seconds


def fetch_prices(symbols: list[str]) -> dict[str, float]:
    """Batch-fetch last prices for the requested symbols from Binance futures."""
    all_tickers = request_json("/fapi/v1/ticker/price")
    by_symbol = {t["symbol"]: float(t["price"]) for t in all_tickers if isinstance(t, dict)}
    out: dict[str, float] = {}
    for s in symbols:
        key = normalize_symbol(s)
        if key in by_symbol:
            out[s] = by_symbol[key]
    return out

APP: "PaperBackend" | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def _as_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _fifo_entry(trades: list[dict[str, Any]], symbol: str) -> tuple[float, float, str | None]:
    lots: list[dict[str, float]] = []
    last_time: str | None = None
    for t in trades:
        if t.get("symbol") != symbol:
            continue
        last_time = t.get("timestamp") or last_time
        side = (t.get("side") or "").upper()
        if side not in ("BUY", "SELL"):
            continue
        qty = abs(_as_float(t.get("qty")))
        price = _as_float(t.get("price"))
        notional = _as_float(t.get("notional"), qty * price)
        fee = _as_float(t.get("fee_paid"))
        if side == "BUY":
            lots.append({"qty": qty, "cost": notional + fee})
        else:
            rem = qty
            while rem > 1e-12 and lots:
                lot = lots[0]
                use = min(lot["qty"], rem)
                cost = lot["cost"] * use / lot["qty"] if lot["qty"] else 0.0
                lot["qty"] -= use
                lot["cost"] -= cost
                rem -= use
                if lot["qty"] <= 1e-12:
                    lots.pop(0)
    total_qty = sum(l["qty"] for l in lots)
    total_cost = sum(l["cost"] for l in lots)
    avg = total_cost / total_qty if total_qty > 1e-12 else 0.0
    return total_qty, avg, last_time


def _process_trades(trades: list[dict[str, Any]]) -> dict[str, Any]:
    lots: dict[str, list[dict[str, float]]] = {}
    sells: list[dict[str, Any]] = []
    total_fees = 0.0
    for t in trades:
        sym = t.get("symbol", "")
        side = (t.get("side") or "").upper()
        qty = abs(_as_float(t.get("qty")))
        price = _as_float(t.get("price"))
        notional = _as_float(t.get("notional"), qty * price)
        fee = _as_float(t.get("fee_paid"))
        total_fees += fee
        if side == "BUY":
            lots.setdefault(sym, []).append({"qty": qty, "notional": notional, "fee": fee})
            continue
        if side != "SELL":
            continue
        sym_lots = lots.get(sym, [])
        rem = qty
        buy_notional = 0.0
        buy_fee = 0.0
        while rem > 1e-12 and sym_lots:
            lot = sym_lots[0]
            use = min(lot["qty"], rem)
            ratio = use / lot["qty"] if lot["qty"] else 0.0
            buy_notional += lot["notional"] * ratio
            buy_fee += lot["fee"] * ratio
            lot["qty"] -= use
            lot["notional"] -= lot["notional"] * ratio
            lot["fee"] -= lot["fee"] * ratio
            rem -= use
            if lot["qty"] <= 1e-12:
                sym_lots.pop(0)
        sold = qty - rem
        entry_price = buy_notional / sold if sold > 1e-12 else 0.0
        gross = notional - buy_notional
        trade_fees = buy_fee + fee
        net = gross - trade_fees
        margin = min(MARGIN_PER_POSITION, notional)
        leverage = notional / margin if margin > 0 else 1.0
        sells.append({
            "timestamp": t.get("timestamp"),
            "symbol": sym,
            "side": side,
            "qty": qty,
            "price": price,
            "notional": notional,
            "entry_price": entry_price,
            "exit_reason": t.get("reason"),
            "gross_pnl": gross,
            "fees": trade_fees,
            "funding": 0.0,
            "net_pnl": net,
            "entry_fee_allocated": buy_fee,
            "total_fees": trade_fees,
            "leverage": leverage,
            "margin": margin,
            "roi_pct": (net / margin * 100.0) if margin > 0 else 0.0,
        })
    pnls = [s["net_pnl"] for s in sells]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_pnls = [s["gross_pnl"] for s in sells]
    gross_wins = [g for g in gross_pnls if g > 0]
    gross_losses = [g for g in gross_pnls if g < 0]
    gl = abs(sum(gross_losses))
    return {
        "realized_gross": sum(gross_pnls),
        "realized_net": sum(pnls),
        "total_fees": total_fees,
        "total_trades": len(sells),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": (len(wins) / len(sells) * 100.0) if sells else 0.0,
        "profit_factor": (sum(gross_wins) / gl) if gl else None,
        "net_pnl": sum(pnls),
        "average_win": (sum(wins) / len(wins)) if wins else None,
        "average_loss": (sum(losses) / len(losses)) if losses else None,
        "largest_win": max(wins) if wins else None,
        "largest_loss": min(losses) if losses else None,
        "recent": list(reversed(sells[-12:])),
    }


class PaperBackend:
    def __init__(self, session_dir: Path) -> None:
        self.session_dir = session_dir
        self.lock = threading.RLock()
        self.started_at = datetime.now(timezone.utc)
        self.last_error: str | None = None

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            try:
                session = _read_json(self.session_dir / "session.json")
                book = _read_json(self.session_dir / "book.json")
                trades = _read_jsonl(self.session_dir / "trades.jsonl")
                marks = _read_jsonl(self.session_dir / "marks.jsonl")
                prices = fetch_prices(session["symbols"])
                self.last_error = None
            except Exception as exc:
                self.last_error = str(exc)
                prices = {}
                session = book = {"initial_cash": 10000.0}
                trades = marks = []

            initial = _as_float(session.get("initial_cash"))
            cash = _as_float(book.get("cash_remaining"))
            fee_rate = _as_float(session.get("fee_rate"), 0.001)
            margin_mode = session.get("risk_config", {}).get("margin_mode", "isolated")
            now = _parse_iso(_now())

            open_positions: list[dict[str, Any]] = []
            for code, qty_raw in book.get("positions", {}).items():
                qty = _as_float(qty_raw)
                if abs(qty) < 1e-12 or code not in prices:
                    continue
                mark = _as_float(prices[code])
                _, avg_entry, last_time = _fifo_entry(trades, code)
                if avg_entry <= 0:
                    avg_entry = _as_float(session.get("entry_prices", {}).get(code))
                direction = 1 if qty > 0 else -1
                side = "LONG" if direction > 0 else "SHORT"
                notional = abs(qty * mark)
                fixed_margin = session.get("risk_config", {}).get("fixed_margin_per_trade", MARGIN_PER_POSITION)
                margin = min(fixed_margin, notional) if fixed_margin > 0 else notional
                pos_leverage = notional / margin if margin > 0 else 1.0
                unreal = (mark - avg_entry) * qty * direction if avg_entry > 0 else 0.0
                roi_pct = (unreal / margin * 100.0) if margin > 0 else 0.0
                last_ts = _now()
                try:
                    base = _parse_iso(last_time) if last_time else now
                    duration = (now - base).total_seconds()
                except Exception:
                    duration = 0.0
                open_positions.append({
                    "trade_id": code,
                    "symbol": code,
                    "side": side,
                    "margin": margin,
                    "leverage": pos_leverage,
                    "notional": notional,
                    "entry_price": avg_entry,
                    "mark_price": mark,
                    "liquidation_price": 0.0,
                    "take_profit": 0.0,
                    "stop_loss": 0.0,
                    "unrealized_pnl": unreal,
                    "roi_pct": roi_pct,
                    "opened_at": last_time,
                    "duration_seconds": int(duration),
                })

            open_notional = sum(p["notional"] for p in open_positions)
            reserved_margin = sum(p["margin"] for p in open_positions)
            unrealized = sum(p["unrealized_pnl"] for p in open_positions)
            tsum = _process_trades(trades)
            realized_gross = tsum["realized_gross"]
            realized_net = tsum["realized_net"]
            fees_paid = tsum["total_fees"]
            wallet = cash + reserved_margin
            available = max(0.0, wallet - reserved_margin)
            equity = wallet + unrealized
            pnl = equity - initial
            pnl_pct = (pnl / initial) if initial else 0.0

            margin_usage_pct = (reserved_margin / wallet * 100.0) if wallet > 0 else 0.0
            equity_loss_pct = max(0.0, (wallet - equity) / wallet * 100.0) if wallet > 0 else 0.0
            penalty = min(55.0, margin_usage_pct * 0.65) + min(35.0, equity_loss_pct * 1.8)
            score = max(0.0, min(100.0, 100.0 - penalty))
            if score >= 85:
                label, risk_level = "Healthy", "Low"
            elif score >= 65:
                label, risk_level = "Watch", "Moderate"
            else:
                label, risk_level = "At Risk", "High"

            recent = tsum["recent"]

            curve = [{"timestamp": m.get("timestamp"), "equity": _as_float(m.get("equity"))} for m in marks[-150:]]
            curve.append({"timestamp": _now(), "equity": equity})

            return {
                "paper_only": True,
                "session_id": self.session_dir.name,
                "engine_status": "connected" if self.last_error is None else "degraded",
                "data_source": "Binance (Mark Price)",
                "last_error": self.last_error,
                "last_refresh_at": _now(),
                "uptime_seconds": int((datetime.now(timezone.utc) - self.started_at).total_seconds()),
                "risk_settings": {
                    "leverage_allowed": "5x / 15x",
                    "margin_range": "$20 - $100",
                    "default_leverage": "10x",
                    "default_margin": "$100",
                    "margin_mode": margin_mode.title() if margin_mode else "Isolated",
                },
                "account": {
                    "timestamp": _now(),
                    "initial_balance": initial,
                    "wallet_balance": wallet,
                    "available_balance": available,
                    "reserved_margin": reserved_margin,
                    "open_notional": open_notional,
                    "realized_gross_pnl": tsum["realized_gross"],
                    "realized_net_pnl": tsum["realized_net"],
                    "unrealized_pnl": unrealized,
                    "fees_paid": fees_paid,
                    "funding_paid": 0.0,
                    "liquidation_fees": 0.0,
                    "current_equity": equity,
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                    "open_positions": open_positions,
                },
                "health": {
                    "score": score,
                    "label": label,
                    "risk_level": risk_level,
                    "margin_usage_pct": margin_usage_pct,
                },
                "stats": {
                    "total_trades": tsum["total_trades"],
                    "wins": tsum["wins"],
                    "losses": tsum["losses"],
                    "win_rate_pct": tsum["win_rate_pct"],
                    "profit_factor": tsum["profit_factor"],
                    "net_pnl": tsum["net_pnl"],
                    "average_win": tsum["average_win"],
                    "average_loss": tsum["average_loss"],
                    "largest_win": tsum["largest_win"],
                    "largest_loss": tsum["largest_loss"],
                },
                "recent_trades": recent,
                "equity_curve": curve,
            }

    def close_symbol(self, symbol: str) -> dict[str, Any]:
        with self.lock:
            session = _read_json(self.session_dir / "session.json")
            book = _read_json(self.session_dir / "book.json")
            trades = _read_jsonl(self.session_dir / "trades.jsonl")
            positions = book.get("positions", {})
            if symbol not in positions or abs(_as_float(positions[symbol])) < 1e-12:
                raise KeyError(f"No open position for {symbol}")

            prices = fetch_prices(session["symbols"])
            if symbol not in prices:
                raise RuntimeError(f"No live price for {symbol}")

            qty = _as_float(positions[symbol])
            mark = _as_float(prices[symbol])
            _, avg_entry, last_time = _fifo_entry(trades, symbol)
            if avg_entry <= 0:
                avg_entry = _as_float(session.get("entry_prices", {}).get(symbol))

            notional = abs(qty * mark)
            fee_rate = _as_float(session.get("fee_rate"), 0.001)
            fee = notional * fee_rate
            direction = 1 if qty > 0 else -1
            gross = (mark - avg_entry) * qty * direction if avg_entry > 0 else 0.0
            net = gross - fee

            cash = _as_float(book.get("cash_remaining"))
            book["cash_remaining"] = cash + notional - fee
            book["positions"][symbol] = 0.0
            book["last_rebalance_time"] = _now()
            receipted_write(self.session_dir / "book.json", json.dumps(book, indent=2))

            trade = {
                "timestamp": _now(),
                "symbol": symbol,
                "side": "SELL" if qty > 0 else "BUY",
                "qty": abs(qty),
                "price": mark,
                "notional": notional,
                "fee_paid": fee,
                "reason": "manual_dashboard",
                "gross_pnl": gross,
                "entry_fee_allocated": None,
                "total_fees": fee,
                "net_pnl": net,
                "realized_pnl": net,
                "entry_time": last_time,
                "entry_price": avg_entry if avg_entry > 0 else None,
            }
            with (self.session_dir / "trades.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(trade, ensure_ascii=False) + "\n")
            return {"ok": True, "net_pnl": net}

    def close_all(self) -> dict[str, Any]:
        with self.lock:
            session = _read_json(self.session_dir / "session.json")
            book = _read_json(self.session_dir / "book.json")
            trades = _read_jsonl(self.session_dir / "trades.jsonl")
            prices = fetch_prices(session["symbols"])
            fee_rate = _as_float(session.get("fee_rate"), 0.001)
            now = _now()
            net_total = 0.0

            for code, qty_raw in list(book.get("positions", {}).items()):
                qty = _as_float(qty_raw)
                if abs(qty) < 1e-12 or code not in prices:
                    continue
                mark = _as_float(prices[code])
                _, avg_entry, last_time = _fifo_entry(trades, code)
                if avg_entry <= 0:
                    avg_entry = _as_float(session.get("entry_prices", {}).get(code))
                notional = abs(qty * mark)
                fee = notional * fee_rate
                direction = 1 if qty > 0 else -1
                gross = (mark - avg_entry) * qty * direction if avg_entry > 0 else 0.0
                net = gross - fee
                net_total += net
                cash = _as_float(book.get("cash_remaining"))
                book["cash_remaining"] = cash + notional - fee
                book["positions"][code] = 0.0
                trade = {
                    "timestamp": now,
                    "symbol": code,
                    "side": "SELL" if qty > 0 else "BUY",
                    "qty": abs(qty),
                    "price": mark,
                    "notional": notional,
                    "fee_paid": fee,
                    "reason": "manual_dashboard_close_all",
                    "gross_pnl": gross,
                    "entry_fee_allocated": None,
                    "total_fees": fee,
                    "net_pnl": net,
                    "realized_pnl": net,
                    "entry_time": last_time,
                    "entry_price": avg_entry if avg_entry > 0 else None,
                }
                trades.append(trade)

            book["last_rebalance_time"] = now
            receipted_write(self.session_dir / "book.json", json.dumps(book, indent=2))
            with (self.session_dir / "trades.jsonl").open("a", encoding="utf-8") as f:
                for t in trades:
                    if t.get("reason", "").startswith("manual_dashboard"):
                        f.write(json.dumps(t, ensure_ascii=False) + "\n")
            return {"ok": True, "closed": len([n for n in []]), "net_pnl": net_total}


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _send_json(handler: BaseHTTPRequestHandler, status: int, payload: Any) -> None:
    body = _json_bytes(payload)
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _read_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", 0) or 0)
    if length <= 0:
        return {}
    return json.loads(handler.rfile.read(length).decode("utf-8"))


def _get_portfolio(sessions_base: Path) -> dict[str, Any]:
    now = time.time()
    cache = PORTFOLIO_CACHE.get("portfolio")
    if cache and now - cache["timestamp"] < PORTFOLIO_CACHE_TTL:
        return cache["data"]

    tab_mapping = {
        "shadow_ab_v1_control_20260711_185947": "Futures Grid",
        "v4_5m_candidate": "Timed Trades",
        "funding_live": "Morning Alpha",
    }
    sessions = [sessions_base / d for d in tab_mapping if (sessions_base / d / "session.json").exists()]

    agg: dict[str, Any] = {
        "initial_balance": 0.0,
        "wallet_balance": 0.0,
        "available_balance": 0.0,
        "reserved_margin": 0.0,
        "open_notional": 0.0,
        "realized_gross_pnl": 0.0,
        "realized_net_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "fees_paid": 0.0,
        "funding_paid": 0.0,
        "liquidation_fees": 0.0,
        "current_equity": 0.0,
        "pnl": 0.0,
        "open_positions": [],
    }
    tabs: list[dict[str, Any]] = []
    recent: list[dict[str, Any]] = []
    total_trades = 0
    wins = 0
    losses = 0
    net_total = 0.0

    for sdir in sessions:
        try:
            backend = PaperBackend(sdir)
            snap = backend.snapshot()
        except Exception:
            continue
        acct = snap.get("account", {})
        for key in agg:
            if key == "open_positions":
                continue
            agg[key] += _as_float(acct.get(key), 0.0)
        pos_count = len(acct.get("open_positions", []))
        initial = _as_float(acct.get("initial_balance"))
        equity = _as_float(acct.get("current_equity"))
        pnl = equity - initial
        st = snap.get("stats", {}) or {}
        tab_wins = int(_as_float(st.get("wins")))
        tab_losses = int(_as_float(st.get("losses")))
        tab_trades = int(_as_float(st.get("total_trades")))
        tab_realized = _as_float(acct.get("realized_net_pnl"))
        tab_unreal = _as_float(acct.get("unrealized_pnl"))
        tab_fees = _as_float(acct.get("fees_paid"))
        # gains and losses from trade stats
        avg_win = _as_float(st.get("average_win")) if st.get("average_win") is not None else 0.0
        avg_loss = _as_float(st.get("average_loss")) if st.get("average_loss") is not None else 0.0
        total_gains = avg_win * tab_wins if avg_win else 0.0
        total_losses = abs(avg_loss) * tab_losses if avg_loss else 0.0
        largest_win = _as_float(st.get("largest_win")) if st.get("largest_win") is not None else 0.0
        largest_loss = _as_float(st.get("largest_loss")) if st.get("largest_loss") is not None else 0.0
        profit_factor = _as_float(st.get("profit_factor")) if st.get("profit_factor") is not None else 0.0
        # risk config from session.json
        try:
            sess_json = _read_json(sdir / "session.json")
            risk_cfg = sess_json.get("risk_config", {}) or {}
        except Exception:
            sess_json = {}
            risk_cfg = {}
        tp_pct = _as_float(risk_cfg.get("take_profit_pct"))
        sl_pct = _as_float(risk_cfg.get("stop_loss_pct"))
        leverage = _as_float(risk_cfg.get("leverage"), 1.0)
        margin_per_trade = _as_float(risk_cfg.get("fixed_margin_per_trade"), 0.0)
        margin_mode = risk_cfg.get("margin_mode", "isolated")
        strategy_type = (sess_json.get("strategy_type", "unknown") if isinstance(sess_json, dict) else "unknown")
        tabs.append({
            "tab": tab_mapping.get(sdir.name, sdir.name),
            "session": sdir.name,
            "strategy_type": strategy_type,
            "equity": equity,
            "initial_cash": initial,
            "pnl": pnl,
            "pnl_pct": (pnl / initial * 100.0) if initial else 0.0,
            "realized_pnl": tab_realized,
            "unrealized_pnl": tab_unreal,
            "fees_paid": tab_fees,
            "total_gains": total_gains,
            "total_losses": total_losses,
            "largest_win": largest_win,
            "largest_loss": largest_loss,
            "profit_factor": profit_factor,
            "wins": tab_wins,
            "losses": tab_losses,
            "total_trades": tab_trades,
            "win_rate_pct": (tab_wins / tab_trades * 100.0) if tab_trades else 0.0,
            "positions": pos_count,
            "reserved_margin": _as_float(acct.get("reserved_margin")),
            "open_notional": _as_float(acct.get("open_notional")),
            "leverage": leverage,
            "margin_per_trade": margin_per_trade,
            "margin_mode": margin_mode,
            "take_profit_pct": tp_pct,
            "stop_loss_pct": sl_pct,
        })
        recent.extend(snap.get("recent_trades", []) or [])
        total_trades += tab_trades
        wins += tab_wins
        losses += tab_losses
        net_total += _as_float(st.get("net_pnl"))

    agg["pnl_pct"] = (agg["pnl"] / agg["initial_balance"]) if agg["initial_balance"] else 0.0
    agg["available_balance"] = max(0.0, agg["wallet_balance"] - agg["reserved_margin"])
    agg["current_equity"] = agg["wallet_balance"] + agg["unrealized_pnl"]
    agg["pnl"] = agg["current_equity"] - agg["initial_balance"]
    agg["pnl_pct"] = (agg["pnl"] / agg["initial_balance"]) if agg["initial_balance"] else 0.0

    wallet = agg["wallet_balance"]
    equity = agg["current_equity"]
    reserved = agg["reserved_margin"]
    margin_usage_pct = (reserved / wallet * 100.0) if wallet > 0 else 0.0
    equity_loss_pct = max(0.0, (wallet - equity) / wallet * 100.0) if wallet > 0 else 0.0
    penalty = min(55.0, margin_usage_pct * 0.65) + min(35.0, equity_loss_pct * 1.8)
    score = max(0.0, min(100.0, 100.0 - penalty))
    if score >= 85:
        label, risk_level = "Healthy", "Low"
    elif score >= 65:
        label, risk_level = "Watch", "Moderate"
    else:
        label, risk_level = "At Risk", "High"

    stats = {
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "win_rate_pct": (wins / total_trades * 100.0) if total_trades else 0.0,
        "profit_factor": None,
        "net_pnl": net_total,
        "average_win": None,
        "average_loss": None,
        "largest_win": None,
        "largest_loss": None,
    }

    result = {
        "paper_only": True,
        "session_id": "portfolio",
        "engine_status": "connected",
        "data_source": "Aggregated",
        "last_refresh_at": _now(),
        "uptime_seconds": 0,
        "risk_settings": {
            "leverage_allowed": "5x / 15x",
            "margin_range": "$20 - $100",
            "default_leverage": "10x",
            "default_margin": "$100",
            "margin_mode": "Isolated",
        },
        "account": agg,
        "tabs": tabs,
        "health": {
            "score": score,
            "label": label,
            "risk_level": risk_level,
            "margin_usage_pct": margin_usage_pct,
        },
        "stats": stats,
        "recent_trades": list(reversed(sorted(recent, key=lambda t: t.get("timestamp", ""))))[:24] if recent else [],
        "equity_curve": [{"timestamp": _now(), "equity": equity}],
    }
    PORTFOLIO_CACHE["portfolio"] = {"timestamp": now, "data": result}
    return result


def make_handler(app: PaperBackend):
    sessions_base = app.session_dir.parent

    def _resolve_session(sid: str | None) -> tuple[PaperBackend | None, str | None]:
        if not sid:
            return app, None
        sdir = Path(sid)
        if not sdir.is_absolute():
            sdir = sessions_base / sid
        if not sdir.is_dir() or not (sdir / "session.json").exists():
            return None, sid
        return PaperBackend(sdir), sid

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: object) -> None:
            return

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            route = parsed.path
            query = parse_qs(parsed.query)
            if route == "/api/status":
                sid = query.get("session", [""])[0] or None
                backend, _ = _resolve_session(sid)
                if backend is None:
                    _send_json(self, 404, {"error": "session_not_found"})
                    return
                _send_json(self, 200, backend.snapshot())
                return
            if route == "/api/sessions":
                sessions = [d.name for d in sessions_base.iterdir() if d.is_dir() and (d / "session.json").exists()]
                _send_json(self, 200, sessions)
                return
            if route == "/api/portfolio":
                _send_json(self, 200, _get_portfolio(sessions_base))
                return
            if route == "/health":
                _send_json(self, 200, {"ok": True, "session_id": app.session_dir.name})
                return
            _send_json(self, 404, {"error": "not_found"})

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            route = parsed.path
            query = parse_qs(parsed.query)
            sid = query.get("session", [""])[0] or None
            backend, _ = _resolve_session(sid)
            if backend is None:
                _send_json(self, 404, {"error": "session_not_found"})
                return
            try:
                if route == "/api/positions/close":
                    body = _read_body(self)
                    trade_id = str(body.get("trade_id", "")).strip()
                    if not trade_id:
                        _send_json(self, 400, {"error": "trade_id required"})
                        return
                    result = backend.close_symbol(trade_id)
                    _send_json(self, 200, result)
                    return
                if route == "/api/session/close-all":
                    result = backend.close_all()
                    _send_json(self, 200, result)
                    return
                _send_json(self, 404, {"error": "not_found"})
            except Exception as exc:
                _send_json(self, 500, {"error": str(exc)})

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Physical paper trading dashboard API")
    parser.add_argument("--session-dir", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()

    global APP
    APP = PaperBackend(Path(args.session_dir))
    server = ThreadingHTTPServer((args.host, args.port), make_handler(APP))
    print(json.dumps({"event": "paper_dashboard_api_started", "url": f"http://{args.host}:{args.port}", "session": str(APP.session_dir)}, indent=2))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
