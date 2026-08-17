#!/usr/bin/env python3
"""Deterministic validation pack for futures accounting."""

from __future__ import annotations

import tempfile
from pathlib import Path

from futures_paper_engine import FuturesPaperEngine, RiskConfig


def approx(a: float, b: float, tol: float = 1e-6) -> None:
    assert abs(a - b) <= tol, (a, b)


def run() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        engine = FuturesPaperEngine(Path(tmp), initial_balance=10_000)

        # 1. $20 margin × 5x profitable long
        p1 = engine.open_position(
            "BTCUSDT", "long", price=100.0,
            risk=RiskConfig(margin=20, leverage=5, take_profit_pct=0.02, stop_loss_pct=0.01),
        )
        assert p1.isolated_margin == 20.0
        assert p1.leverage == 5
        approx(p1.notional, 100.0)
        approx(engine.state.reserved_margin, 20.0)
        closed1 = engine.process_price(p1.trade_id, 102.0)
        assert closed1 is not None
        assert closed1.exit_reason == "take_profit"
        assert closed1.net_pnl > 0
        approx(engine.state.reserved_margin, 0.0)

        # 2. $100 margin × 10x losing short
        p2 = engine.open_position(
            "ETHUSDT", "short", price=100.0,
            risk=RiskConfig(margin=100, leverage=10, take_profit_pct=0.01, stop_loss_pct=0.005),
        )
        assert p2.isolated_margin == 100.0
        assert p2.leverage == 10
        approx(p2.notional, 1000.0)
        closed2 = engine.process_price(p2.trade_id, 100.5)
        assert closed2 is not None
        assert closed2.exit_reason == "stop_loss"
        assert closed2.net_pnl < 0

        # 3. TP execution (already covered by case 1, expand with explicit net TP math)
        p3 = engine.open_position(
            "BTCUSDT", "long", price=100.0,
            risk=RiskConfig(margin=50, leverage=5, take_profit_pct=0.01, stop_loss_pct=0.005),
        )
        expected_tp_gross = p3.notional * 0.01
        closed3 = engine.process_price(p3.trade_id, 101.0)
        assert closed3 is not None and closed3.exit_reason == "take_profit"
        approx(closed3.gross_pnl, expected_tp_gross)

        # 4. SL execution (already covered by case 2)
        p4 = engine.open_position(
            "ETHUSDT", "long", price=100.0,
            risk=RiskConfig(margin=50, leverage=5, take_profit_pct=0.02, stop_loss_pct=0.01),
        )
        closed4 = engine.process_price(p4.trade_id, 99.0)
        assert closed4 is not None and closed4.exit_reason == "stop_loss"
        assert closed4.net_pnl < 0

        # 5. Trailing-stop execution
        p5 = engine.open_position(
            "SOLUSDT", "long", price=100.0,
            risk=RiskConfig(
                margin=50, leverage=5,
                take_profit_pct=0.10, stop_loss_pct=0.10,
                trailing_stop_pct=0.02,
            ),
        )
        engine.process_price(p5.trade_id, 110.0)  # set high-water mark
        closed5 = engine.process_price(p5.trade_id, 107.8)  # 2% trail from 110
        assert closed5 is not None and closed5.exit_reason == "trailing_stop"

        # 6. Long funding payment
        p6 = engine.open_position(
            "ADAUSDT", "long", price=100.0,
            risk=RiskConfig(margin=50, leverage=5, take_profit_pct=0.10, stop_loss_pct=0.10),
        )
        payment = engine.apply_funding(p6.trade_id, 0.0001)
        assert payment > 0  # long pays positive funding
        engine.close_position(p6.trade_id, price=100.0)

        # 7. Short funding receipt
        p7 = engine.open_position(
            "DOGEUSDT", "short", price=100.0,
            risk=RiskConfig(margin=50, leverage=5, take_profit_pct=0.10, stop_loss_pct=0.10),
        )
        receipt = engine.apply_funding(p7.trade_id, 0.0001)
        assert receipt < 0  # short receives (negative payment from long perspective)
        engine.close_position(p7.trade_id, price=100.0)

        # 8. Isolated liquidation
        p8 = engine.open_position(
            "LINKUSDT", "long", price=100.0,
            risk=RiskConfig(margin=50, leverage=5, take_profit_pct=2.0, stop_loss_pct=0.19, maintenance_margin_rate=1e-9),
        )
        liq_price = p8.liquidation_price
        closed8 = engine.process_price(p8.trade_id, liq_price)
        assert closed8 is not None and closed8.exit_reason == "liquidation"

        # 9. Insufficient available-margin rejection
        engine2 = FuturesPaperEngine(Path(tmp) / "margin_test", initial_balance=20.0)
        try:
            engine2.open_position(
                "BTCUSDT", "long", price=100.0,
                risk=RiskConfig(margin=100, leverage=5),
            )
            raise AssertionError("expected insufficient balance rejection")
        except RuntimeError as exc:
            assert "insufficient available balance" in str(exc)

        # 10. Two simultaneous isolated positions
        engine3 = FuturesPaperEngine(Path(tmp) / "two_positions", initial_balance=10_000)
        a = engine3.open_position(
            "BTCUSDT", "long", price=100.0,
            risk=RiskConfig(margin=50, leverage=5, take_profit_pct=0.10, stop_loss_pct=0.10),
        )
        b = engine3.open_position(
            "ETHUSDT", "short", price=100.0,
            risk=RiskConfig(margin=50, leverage=5, take_profit_pct=0.10, stop_loss_pct=0.10),
        )
        assert a.trade_id != b.trade_id
        approx(engine3.state.reserved_margin, 100.0)

        # 11. Fee reconciliation
        fee_sum = (
            sum(t["entry_fee"] + t["exit_fee"] for t in engine3.closed_trades())
            + sum(p.entry_fee for p in engine3.state.positions.values())
        )
        assert abs(fee_sum - engine3.state.total_fees) < 1e-6

        # 12. Wallet-equity reconciliation
        snapshot = engine3.account_summary({"BTCUSDT": 100.0, "ETHUSDT": 100.0})
        expected_equity = snapshot["wallet_balance"] + snapshot["unrealized_pnl"]
        approx(snapshot["current_equity"], expected_equity)
        assert engine3.state.available_balance >= 0

    print("All futures accounting validation tests passed.")


if __name__ == "__main__":
    run()
