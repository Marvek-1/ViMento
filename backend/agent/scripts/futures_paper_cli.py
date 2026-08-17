#!/usr/bin/env python3
"""CLI for MoStar Futures Paper Engine."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from futures_paper_engine import (
    FeeSchedule,
    FuturesPaperEngine,
    RiskConfig,
    run_poll_loop,
)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Paper-only Binance USDT-M futures simulator")
    p.add_argument("--session", default="paper_sessions/default", help="session directory")
    p.add_argument("--initial-balance", type=float, default=10_000.0)
    p.add_argument("--maker-fee", type=float, default=0.0002)
    p.add_argument("--taker-fee", type=float, default=0.0005)
    sub = p.add_subparsers(dest="command", required=True)

    open_p = sub.add_parser("open")
    open_p.add_argument("symbol")
    open_p.add_argument("side", choices=["long", "short"])
    open_p.add_argument("--price", type=float)
    open_p.add_argument("--margin", type=float, default=50.0)
    open_p.add_argument("--leverage", type=int, choices=[5, 10], default=5)
    open_p.add_argument("--margin-mode", choices=["isolated", "cross"], default="isolated")
    open_p.add_argument("--tp", type=float, default=0.012, help="price move fraction, e.g. 0.012")
    open_p.add_argument("--sl", type=float, default=0.006, help="price move fraction, e.g. 0.006")
    open_p.add_argument("--trailing", type=float)
    open_p.add_argument("--max-hold-minutes", type=int)
    open_p.add_argument("--reason", default="manual")
    open_p.add_argument("--regime", default="unknown")

    close_p = sub.add_parser("close")
    close_p.add_argument("trade_id")
    close_p.add_argument("--price", type=float)
    close_p.add_argument("--reason", default="manual")

    mark_p = sub.add_parser("mark")
    mark_p.add_argument("--prices-json", help='example: {"BTCUSDT":65000}')

    funding_p = sub.add_parser("funding")
    funding_p.add_argument("trade_id")
    funding_p.add_argument("rate", type=float)

    sub.add_parser("positions")
    sub.add_parser("trades")

    cycle_p = sub.add_parser("cycle")
    cycle_p.add_argument("--since")
    cycle_p.add_argument("--until")

    run_p = sub.add_parser("run")
    run_p.add_argument("--poll-seconds", type=int, default=5)
    run_p.add_argument("--apply-funding", action="store_true")
    return p


def main() -> None:
    args = parser().parse_args()
    engine = FuturesPaperEngine(
        Path(args.session),
        initial_balance=args.initial_balance,
        fee_schedule=FeeSchedule(maker=args.maker_fee, taker=args.taker_fee),
    )

    if args.command == "open":
        risk = RiskConfig(
            margin_mode=args.margin_mode,
            leverage=args.leverage,
            margin=args.margin,
            take_profit_pct=args.tp,
            stop_loss_pct=args.sl,
            trailing_stop_pct=args.trailing,
            max_hold_minutes=args.max_hold_minutes,
        )
        result = engine.open_position(
            args.symbol,
            args.side,
            price=args.price,
            risk=risk,
            signal_reason=args.reason,
            market_regime=args.regime,
        )
        print(json.dumps(asdict(result), indent=2))

    elif args.command == "close":
        print(json.dumps(asdict(engine.close_position(
            args.trade_id, price=args.price, exit_reason=args.reason
        )), indent=2))

    elif args.command == "mark":
        prices = json.loads(args.prices_json) if args.prices_json else None
        print(json.dumps(engine.account_summary(prices), indent=2))

    elif args.command == "funding":
        print(json.dumps({"payment": engine.apply_funding(args.trade_id, args.rate)}, indent=2))

    elif args.command == "positions":
        print(json.dumps(engine.account_summary(), indent=2))

    elif args.command == "trades":
        print(json.dumps(engine.closed_trades(), indent=2))

    elif args.command == "cycle":
        print(json.dumps(engine.cycle_report(args.since, args.until), indent=2))

    elif args.command == "run":
        run_poll_loop(engine, poll_seconds=args.poll_seconds, apply_funding=args.apply_funding)


if __name__ == "__main__":
    main()
