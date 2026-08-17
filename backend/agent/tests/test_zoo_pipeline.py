from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from research import backtest, walkforward
from research.alpha_adapter import alpha_to_strategy
from research.zoo_pipeline import build_paper_handoff, evaluate_readiness, write_pipeline_artifacts
from src.factors import registry as factor_registry
from src.tools import alpha_bench_tool


def test_binance_perps_loader_enforces_complete_ohlcv_rows(tmp_path: Path, monkeypatch) -> None:
    universe_file = tmp_path / "universe.txt"
    universe_file.write_text("AAA-USDT,BBB-USDT", encoding="utf-8")
    timestamps = pd.date_range("2025-01-01", periods=3, freq="h", tz="UTC")
    ts_ms = [int(value.timestamp() * 1000) for value in timestamps]

    def bars(symbol: str, timeframe: str, data_dir: Path) -> pd.DataFrame:
        frame = pd.DataFrame(
            {
                "ts": ts_ms,
                "open": [1.0, 2.0, 3.0],
                "high": [1.0, 2.0, 3.0],
                "low": [1.0, 2.0, 3.0],
                "close": [1.0, 2.0, 3.0],
                "volume": [1.0, 1.0, 1.0],
            }
        )
        if symbol == "BBB-USDT":
            frame.loc[1, "volume"] = float("nan")
        return frame

    monkeypatch.setattr(alpha_bench_tool, "_BINANCE_PERPS_34_UNIVERSE_FILE", universe_file)
    monkeypatch.setattr(alpha_bench_tool, "load_bars", bars)
    panel = alpha_bench_tool._load_binance_perps_34_panel("2025-01-01", "2025-01-01")

    assert list(panel["close"].columns) == ["AAA-USDT", "BBB-USDT"]
    assert len(panel["close"]) == 2
    assert panel["volume"].notna().all().all()


def test_alpha_adapter_selects_top_n_at_current_timestamp(monkeypatch) -> None:
    index = pd.Index([1, 2])
    factors = pd.DataFrame(
        {"AAA": [3.0, 1.0], "BBB": [2.0, 3.0], "CCC": [1.0, 2.0]},
        index=index,
    )

    class FakeRegistry:
        def compute(self, alpha_id, panel):
            return factors

    monkeypatch.setattr(factor_registry, "get_default_registry", lambda: FakeRegistry())
    panel = {"close": pd.DataFrame({"AAA": [1.0, 1.0], "BBB": [1.0, 1.0], "CCC": [1.0, 1.0]}, index=index)}
    strategy = alpha_to_strategy("alpha101_001", panel, top_n=2)

    assert strategy(panel["close"].iloc[:1]) == {"AAA": 0.5, "BBB": 0.5}
    assert strategy(panel["close"]) == {"BBB": 0.5, "CCC": 0.5}


def test_gauntlet_selects_on_validation_not_test(monkeypatch) -> None:
    validate = pd.DataFrame({"AAA": [1.0, 2.0, 3.0], "BBB": [3.0, 2.0, 1.0]})
    test = pd.DataFrame({"AAA": [3.0, 2.0, 1.0], "BBB": [1.0, 2.0, 3.0]})
    split = walkforward.Split(
        name="split_1",
        prices=pd.concat([validate, test], ignore_index=True),
        train=None,
        validate=validate,
        test=test,
    )
    monkeypatch.setattr(walkforward, "make_splits", lambda prices, n_splits: [split])

    def hold(symbol: str):
        return lambda prices: {symbol: 1.0}

    result = walkforward.run_gauntlet(
        split.prices,
        candidates={"validation_winner": hold("AAA"), "test_winner": hold("BBB")},
        baselines={},
        fee_rate=0.0,
        slippage_rate=0.0,
        n_splits=1,
        rebalance_every=10,
    )

    assert list(result["selected_per_split"]["split_1"]) == ["validation_winner"]
    assert result["test_summary"]["validation_winner"]["total_return"] < 0
    assert "test_winner" not in result["test_summary"]


def test_readiness_requires_every_gate() -> None:
    result = {
        "selected_per_split": {
            "split_1": {"alpha_ok": 1.0},
            "split_2": {"alpha_ok": 0.8},
        },
        "test_summary": {
            "alpha_ok": {
                "total_return": 0.12,
                "profit_factor": 1.4,
                "max_drawdown": -0.1,
                "closed_trades": 20.0,
            },
            "equal_weight": {"total_return": 0.04},
        },
    }

    rows = evaluate_readiness(
        result,
        ["alpha_ok"],
        min_profit_factor=1.2,
        min_test_splits=2,
        min_trades=30,
        max_drawdown=0.25,
        benchmark_name="equal_weight",
    )

    assert rows[0]["qualified_for_shadow_paper"] is True
    assert rows[0]["total_closed_trades"] == 40
    assert rows[0]["return_edge_vs_benchmark"] == pytest.approx(0.08)


def test_paper_handoff_is_shadow_only_and_not_armed() -> None:
    readiness = [
        {
            "alpha_id": "alpha101_001",
            "qualified_for_shadow_paper": True,
            "gates": {"minimum_closed_trades": True},
            "metrics": {"total_return": 0.1},
        }
    ]

    handoff = build_paper_handoff(
        readiness,
        universe="binance_perps_34",
        period="2025-01-01/2025-12-31",
        symbols=["BTC-USDT", "ETH-USDT"],
        top_n=2,
        fee_rate=0.001,
        slippage_rate=0.0005,
        rebalance_every=1,
        take_profit=0.05,
        stop_loss=0.03,
    )

    assert handoff["destination"] == "paper_trading_shadow_only"
    assert handoff["production_authority"] == "none"
    assert handoff["auto_start"] is False
    assert handoff["candidates"][0]["auto_start"] is False


def test_profit_factor_uses_realized_closed_trades() -> None:
    curve = pd.Series([100.0, 101.0, 100.0, 102.0])
    metrics = backtest.compute_metrics(curve, 365.0, [30.0, -10.0])

    assert metrics["profit_factor"] == pytest.approx(3.0)
    assert metrics["closed_trades"] == 2.0
    assert metrics["expectancy"] == pytest.approx(10.0)
    assert metrics["return_profit_factor"] != metrics["profit_factor"]


def test_pipeline_artifacts_are_receipted_and_strict_json(tmp_path: Path) -> None:
    result = {
        "paper_handoff": {"candidates": [], "auto_start": False},
        "gauntlet": {"profit_factor": float("inf")},
    }

    receipts = write_pipeline_artifacts(result, tmp_path / "research.json")

    research_path = Path(receipts["research"]["path"])
    paper_path = Path(receipts["paper_handoff"]["path"])
    assert receipts["research"]["bytes_written"] == research_path.stat().st_size
    assert receipts["paper_handoff"]["bytes_written"] == paper_path.stat().st_size
    assert json.loads(research_path.read_text(encoding="utf-8"))["gauntlet"]["profit_factor"] is None
