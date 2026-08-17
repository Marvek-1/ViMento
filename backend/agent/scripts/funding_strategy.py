"""Funding-rate z-score backtest engine.

Strategy logic:
  - Fetch historical funding rates and OHLCV price data for each symbol.
  - Compute a rolling z-score of the funding rate over a configurable window.
  - When z-score <= -entry_z (extremely negative funding), go long: shorts
    pay longs, so negative funding is a tailwind for longs.
  - When z-score >= +entry_z (extremely positive funding), go short: longs
    pay shorts.
  - Exit when |z-score| falls below exit_z (mean-reversion of the signal).
  - Simulate P&L with realistic taker fees, slippage, and actual funding
    payments/receipts at each settlement.

This is a standalone backtest -- it does not touch the paper-session
infrastructure.  See ``paper_session.py``'s ``funding_rate_zscore`` strategy
type for live paper integration.

Usage:
    python agent/funding_strategy.py backtest \\
        --symbols BTC-USDT,ETH-USDT,SOL-USDT \\
        --start 2025-01-01 \\
        --end 2025-07-01 \\
        --z-window 120 \\
        --entry-z 1.5 \\
        --exit-z 0.5 \\
        --initial-capital 10000 \\
        --fee-rate 0.0005 \\
        --slippage 0.0005
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest.loaders.funding_rate_loader import fetch_funding_rate_history


@dataclass
class FundingBacktestConfig:
    symbols: List[str]
    start_date: str
    end_date: str
    z_window: int = 120          # rolling window (number of funding intervals)
    entry_z: float = 1.5         # |z| threshold to open a position
    exit_z: float = 0.5          # |z| threshold to close (mean-reverted)
    initial_capital: float = 10_000.0
    fee_rate: float = 0.0005     # taker fee per trade
    slippage_rate: float = 0.0005  # half-spread slippage
    max_position_pct: float = 0.25  # max fraction of equity per symbol
    funding_interval_hours: int = 8   # Binance default


@dataclass
class TradeRecord:
    timestamp: pd.Timestamp
    symbol: str
    side: str        # "LONG" / "SHORT" / "CLOSE"
    qty: float
    price: float
    notional: float
    fee: float
    reason: str


@dataclass
class EquityPoint:
    timestamp: pd.Timestamp
    equity: float
    cash: float
    positions_value: float
    funding_pnl: float
    price_pnl: float


@dataclass
class BacktestResult:
    config: FundingBacktestConfig
    equity_curve: pd.DataFrame
    trades: List[TradeRecord]
    metrics: Dict[str, Any]
    per_symbol_metrics: Dict[str, Dict[str, Any]]


def _load_ohlcv(symbols: List[str], start_date: str, end_date: str) -> Dict[str, pd.DataFrame]:
    """Load daily OHLCV for price simulation via the existing binance loader."""
    from backtest.loaders.binance_loader import DataLoader
    loader = DataLoader()
    return loader.fetch(symbols, start_date, end_date, interval="1D")


def _compute_zscore(funding_df: pd.DataFrame, window: int) -> pd.DataFrame:
    """Add a rolling z-score column to the funding-rate DataFrame."""
    df = funding_df.copy()
    col = "funding_rate"
    rolling = df[col].rolling(window=window, min_periods=max(10, window // 3))
    df["z_score"] = (df[col] - rolling.mean()) / rolling.std()
    df["z_score"] = df["z_score"].replace([np.inf, -np.inf], np.nan)
    return df


def _merge_funding_and_price(
    funding: Dict[str, pd.DataFrame],
    prices: Dict[str, pd.DataFrame],
) -> Dict[str, pd.DataFrame]:
    """Forward-fill daily close onto funding timestamps for each symbol."""
    merged: Dict[str, pd.DataFrame] = {}
    for sym, fdf in funding.items():
        if sym not in prices:
            continue
        pdf = prices[sym][["close"]].copy()
        pdf.index = pdf.index.tz_localize("UTC") if pdf.index.tz is None else pdf.index
        # Reindex daily close onto funding timestamps, forward-fill
        combined = fdf.join(
            pdf.rename(columns={"close": "price"}),
            how="left",
        )
        combined["price"] = combined["price"].ffill()
        # If the first funding rows predate the first price bar, back-fill
        combined["price"] = combined["price"].bfill()
        merged[sym] = combined
    return merged


def run_funding_backtest(config: FundingBacktestConfig) -> BacktestResult:
    """Run the funding-rate z-score backtest.

    Steps:
      1. Fetch funding-rate history and daily OHLCV.
      2. Compute rolling z-scores.
      3. Walk through each funding settlement bar-by-bar.
      4. Generate signals: long when z <= -entry_z, short when z >= +entry_z.
      5. Exit when |z| < exit_z.
      6. Simulate P&L: price change + funding payment/receipt - fees - slippage.
    """
    # 1. Fetch data
    funding_raw = fetch_funding_rate_history(
        config.symbols, config.start_date, config.end_date,
    )
    prices_raw = _load_ohlcv(config.symbols, config.start_date, config.end_date)

    # 2. Compute z-scores and merge with prices
    funding_z: Dict[str, pd.DataFrame] = {}
    for sym, fdf in funding_raw.items():
        funding_z[sym] = _compute_zscore(fdf, config.z_window)

    merged = _merge_funding_and_price(funding_z, prices_raw)

    if not merged:
        return BacktestResult(
            config=config,
            equity_curve=pd.DataFrame(columns=["timestamp", "equity"]),
            trades=[],
            metrics={"error": "no data after merge"},
            per_symbol_metrics={},
        )

    # 3. Build a unified timeline across all symbols
    all_timestamps = sorted(set(
        ts for df in merged.values() for ts in df.index
        if pd.notna(df.loc[ts, "z_score"])
    ))

    # 4. Walk through timeline
    cash = config.initial_capital
    positions: Dict[str, Dict[str, Any]] = {}  # sym -> {direction, qty, entry_price}
    trades: List[TradeRecord] = []
    equity_points: List[EquityPoint] = []
    cumulative_funding_pnl = 0.0
    cumulative_price_pnl = 0.0

    for ts in all_timestamps:
        # Mark-to-market existing positions at current price
        positions_value = 0.0
        for sym, pos in positions.items():
            df = merged.get(sym)
            if df is None or ts not in df.index:
                continue
            price = float(df.loc[ts, "price"])
            if pd.isna(price):
                continue
            pos_value = pos["qty"] * price * pos["direction"]
            positions_value += pos_value

            # Funding settlement: longs pay positive funding, shorts receive
            funding_rate = float(df.loc[ts, "funding_rate"])
            if pd.notna(funding_rate):
                notional = pos["qty"] * price
                funding_payment = -notional * funding_rate * pos["direction"]
                cash += funding_payment
                cumulative_funding_pnl += funding_payment

        equity = cash + positions_value

        # Generate signals and trade
        for sym in config.symbols:
            df = merged.get(sym)
            if df is None or ts not in df.index:
                continue

            z = df.loc[ts, "z_score"]
            price = df.loc[ts, "price"]
            if pd.isna(z) or pd.isna(price):
                continue

            price = float(price)
            z = float(z)
            current = positions.get(sym)

            # Signal logic
            if current is None:
                # Entry signals
                if z <= -config.entry_z:
                    # Go long: negative funding means shorts pay longs
                    target_notional = equity * config.max_position_pct
                    qty = target_notional / price
                    exec_price = price * (1 + config.slippage_rate)
                    fee = qty * exec_price * config.fee_rate
                    cash -= qty * exec_price + fee
                    positions[sym] = {"direction": 1, "qty": qty, "entry_price": exec_price}
                    trades.append(TradeRecord(
                        timestamp=ts, symbol=sym, side="LONG",
                        qty=qty, price=exec_price,
                        notional=qty * exec_price, fee=fee,
                        reason=f"z={z:.2f}",
                    ))
                    cumulative_price_pnl -= fee

                elif z >= config.entry_z:
                    # Go short: positive funding means longs pay shorts
                    target_notional = equity * config.max_position_pct
                    qty = target_notional / price
                    exec_price = price * (1 - config.slippage_rate)
                    fee = qty * exec_price * config.fee_rate
                    cash += qty * exec_price - fee
                    positions[sym] = {"direction": -1, "qty": qty, "entry_price": exec_price}
                    trades.append(TradeRecord(
                        timestamp=ts, symbol=sym, side="SHORT",
                        qty=qty, price=exec_price,
                        notional=qty * exec_price, fee=fee,
                        reason=f"z={z:.2f}",
                    ))
                    cumulative_price_pnl -= fee

            else:
                # Exit signal: z-score has reverted
                if abs(z) < config.exit_z:
                    pos = current
                    if pos["direction"] == 1:
                        exec_price = price * (1 - config.slippage_rate)
                        fee = pos["qty"] * exec_price * config.fee_rate
                        proceeds = pos["qty"] * exec_price - fee
                        cash += proceeds
                        pnl = proceeds - pos["qty"] * pos["entry_price"]
                        cumulative_price_pnl += pnl
                    else:
                        exec_price = price * (1 + config.slippage_rate)
                        fee = pos["qty"] * exec_price * config.fee_rate
                        cost = pos["qty"] * exec_price + fee
                        cash -= cost
                        pnl = pos["qty"] * pos["entry_price"] - cost
                        cumulative_price_pnl += pnl

                    trades.append(TradeRecord(
                        timestamp=ts, symbol=sym, side="CLOSE",
                        qty=pos["qty"], price=exec_price,
                        notional=pos["qty"] * exec_price, fee=fee,
                        reason=f"z={z:.2f}",
                    ))
                    del positions[sym]

        # Recompute equity after trades
        positions_value = sum(
            pos["qty"] * float(merged[sym].loc[ts, "price"]) * pos["direction"]
            for sym, pos in positions.items()
            if sym in merged and ts in merged[sym].index and pd.notna(merged[sym].loc[ts, "price"])
        )
        equity = cash + positions_value

        equity_points.append(EquityPoint(
            timestamp=ts,
            equity=equity,
            cash=cash,
            positions_value=positions_value,
            funding_pnl=cumulative_funding_pnl,
            price_pnl=cumulative_price_pnl,
        ))

    # 5. Close any remaining positions at the last price
    last_ts = all_timestamps[-1] if all_timestamps else None
    if last_ts:
        for sym, pos in list(positions.items()):
            df = merged.get(sym)
            if df is None or last_ts not in df.index:
                continue
            price = float(df.loc[last_ts, "price"])
            if pd.isna(price):
                continue
            if pos["direction"] == 1:
                exec_price = price * (1 - config.slippage_rate)
                fee = pos["qty"] * exec_price * config.fee_rate
                cash += pos["qty"] * exec_price - fee
            else:
                exec_price = price * (1 + config.slippage_rate)
                fee = pos["qty"] * exec_price * config.fee_rate
                cash -= pos["qty"] * exec_price + fee
            trades.append(TradeRecord(
                timestamp=last_ts, symbol=sym, side="CLOSE",
                qty=pos["qty"], price=exec_price,
                notional=pos["qty"] * exec_price, fee=fee,
                reason="end_of_backtest",
            ))
            del positions[sym]

    # 6. Compute metrics
    equity_df = pd.DataFrame([
        {"timestamp": p.timestamp, "equity": p.equity, "cash": p.cash,
         "positions_value": p.positions_value,
         "funding_pnl": p.funding_pnl, "price_pnl": p.price_pnl}
        for p in equity_points
    ])
    if not equity_df.empty:
        equity_df = equity_df.set_index("timestamp")

    metrics = _compute_metrics(equity_df, trades, config)
    per_symbol = _compute_per_symbol_metrics(trades, merged)

    return BacktestResult(
        config=config,
        equity_curve=equity_df,
        trades=trades,
        metrics=metrics,
        per_symbol_metrics=per_symbol,
    )


def _compute_metrics(
    equity_df: pd.DataFrame,
    trades: List[TradeRecord],
    config: FundingBacktestConfig,
) -> Dict[str, Any]:
    if equity_df.empty:
        return {"error": "no equity points"}

    eq = equity_df["equity"]
    total_return = (eq.iloc[-1] - config.initial_capital) / config.initial_capital

    # Daily returns from equity curve
    daily_eq = eq.resample("1D").last().dropna()
    if len(daily_eq) < 2:
        daily_returns = pd.Series(dtype=float)
    else:
        daily_returns = daily_eq.pct_change().dropna()

    if daily_returns.empty:
        sharpe = 0.0
        sortino = 0.0
        max_drawdown = 0.0
    else:
        ann_factor = 365  # crypto trades 24/7
        sharpe = float(
            daily_returns.mean() / daily_returns.std() * np.sqrt(ann_factor)
        ) if daily_returns.std() > 0 else 0.0

        downside = daily_returns[daily_returns < 0]
        sortino = float(
            daily_returns.mean() / downside.std() * np.sqrt(ann_factor)
        ) if len(downside) > 1 and downside.std() > 0 else 0.0

        running_max = daily_eq.cummax()
        drawdown = (daily_eq - running_max) / running_max
        max_drawdown = float(drawdown.min())

    # Trade stats
    longs = [t for t in trades if t.side in ("LONG", "SHORT")]
    closes = [t for t in trades if t.side == "CLOSE"]
    total_fees = sum(t.fee for t in trades)

    # Funding P&L (last cumulative value)
    funding_pnl = float(equity_df["funding_pnl"].iloc[-1]) if "funding_pnl" in equity_df.columns else 0.0
    price_pnl = float(equity_df["price_pnl"].iloc[-1]) if "price_pnl" in equity_df.columns else 0.0

    return {
        "total_return": total_return,
        "total_return_pct": total_return * 100,
        "final_equity": float(eq.iloc[-1]),
        "initial_capital": config.initial_capital,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_drawdown,
        "max_drawdown_pct": max_drawdown * 100,
        "total_trades": len(trades),
        "entry_trades": len(longs),
        "close_trades": len(closes),
        "total_fees": total_fees,
        "funding_pnl": funding_pnl,
        "price_pnl": price_pnl,
        "symbols": config.symbols,
        "z_window": config.z_window,
        "entry_z": config.entry_z,
        "exit_z": config.exit_z,
    }


def _compute_per_symbol_metrics(
    trades: List[TradeRecord],
    merged: Dict[str, pd.DataFrame],
) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    for sym in merged:
        sym_trades = [t for t in trades if t.symbol == sym]
        entries = [t for t in sym_trades if t.side in ("LONG", "SHORT")]
        closes = [t for t in sym_trades if t.side == "CLOSE"]
        fees = sum(t.fee for t in sym_trades)
        result[sym] = {
            "entries": len(entries),
            "closes": len(closes),
            "fees": fees,
        }
    return result


def _cli() -> None:
    parser = argparse.ArgumentParser(description="Funding-rate z-score backtest")
    sub = parser.add_subparsers(dest="command", required=True)

    p_bt = sub.add_parser("backtest", help="Run a backtest")
    p_bt.add_argument("--symbols", required=True, help="Comma-separated, e.g. BTC-USDT,ETH-USDT")
    p_bt.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    p_bt.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    p_bt.add_argument("--z-window", type=int, default=120)
    p_bt.add_argument("--entry-z", type=float, default=1.5)
    p_bt.add_argument("--exit-z", type=float, default=0.5)
    p_bt.add_argument("--initial-capital", type=float, default=10_000.0)
    p_bt.add_argument("--fee-rate", type=float, default=0.0005)
    p_bt.add_argument("--slippage", type=float, default=0.0005)
    p_bt.add_argument("--max-position-pct", type=float, default=0.25)
    p_bt.add_argument("--output", type=Path, default=None, help="Save equity curve as CSV")

    args = parser.parse_args()

    if args.command == "backtest":
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        config = FundingBacktestConfig(
            symbols=symbols,
            start_date=args.start,
            end_date=args.end,
            z_window=args.z_window,
            entry_z=args.entry_z,
            exit_z=args.exit_z,
            initial_capital=args.initial_capital,
            fee_rate=args.fee_rate,
            slippage_rate=args.slippage,
            max_position_pct=args.max_position_pct,
        )
        result = run_funding_backtest(config)

        print(json.dumps({"metrics": result.metrics}, indent=2, default=str))
        print(json.dumps({"per_symbol": result.per_symbol_metrics}, indent=2, default=str))

        if args.output and not result.equity_curve.empty:
            result.equity_curve.to_csv(args.output)
            print(f"Equity curve saved to {args.output}")


if __name__ == "__main__":
    _cli()
