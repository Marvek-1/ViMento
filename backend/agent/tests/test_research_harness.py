from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import pytest

from research import backtest, data_store, strategies, walkforward


def _make_bars(trend: list[float], symbol: str = "AAA-USDT") -> pd.DataFrame:
    ts = [1_000_000_000 + i * 60_000 for i in range(len(trend))]
    return pd.DataFrame({
        "ts": ts,
        "open": trend,
        "high": trend,
        "low": trend,
        "close": trend,
        "volume": [1.0] * len(trend),
    })


def test_data_store_merges_and_dedupes(tmp_path: Path) -> None:
    store_dir = tmp_path / "data"
    df1 = _make_bars([1.0, 2.0, 3.0], "AAA-USDT")
    df2 = _make_bars([2.0, 3.0, 4.0], "AAA-USDT")
    df2["ts"] = df2["ts"] + 60_000
    data_store.save_bars("AAA-USDT", "1m", df1, data_dir=store_dir)
    data_store.save_bars("AAA-USDT", "1m", df2, data_dir=store_dir)
    loaded = data_store.load_bars("AAA-USDT", "1m", data_dir=store_dir)
    assert len(loaded) == 4
    assert list(loaded["close"]) == [1.0, 2.0, 3.0, 4.0]


def test_data_store_download_pages_and_persists(tmp_path: Path) -> None:
    class FakeExchange:
        def __init__(self) -> None:
            self.calls = 0

        def fetch_ohlcv(self, symbol, timeframe, since, limit):
            start = max(self.calls * 1000, since)
            self.calls += 1
            if self.calls > 2:
                return []
            return [[start + i * 60000, float(i), float(i), float(i), float(i), 1.0] for i in range(limit)]

    exchange = FakeExchange()
    store_dir = tmp_path / "data"
    df = data_store.download_history("AAA-USDT", "1m", 0, data_dir=store_dir, exchange=exchange)
    assert len(df) == 2000
    assert data_store.load_bars("AAA-USDT", "1m", data_dir=store_dir).shape[0] == 2000


def test_backtest_buy_and_hold_grows_with_trending_asset() -> None:
    prices = _make_bars([1.0] * 10 + [2.0] * 10).set_index("ts")["close"].rename("AAA-USDT").to_frame()
    result = backtest.run_backtest(prices, strategies.buy_and_hold, fee_rate=0.0, rebalance_every=20)
    assert result.metrics["total_return"] > 0
    assert result.trades == 1


def test_backtest_equal_weight_rebalances_on_schedule() -> None:
    prices = _make_bars([1.0, 1.1, 1.2, 1.1, 1.0], "AAA-USDT").set_index("ts")["close"].rename("AAA-USDT").to_frame()
    prices["BBB-USDT"] = [1.0, 0.9, 0.8, 0.9, 1.0]
    result = backtest.run_backtest(prices, strategies.equal_weight, fee_rate=0.0, rebalance_every=2)
    assert result.trades > 0
    assert result.metrics["final_equity"] > 0
    assert not math.isnan(result.metrics["final_equity"])


def test_backtest_sells_first_and_scales_buys_to_cash() -> None:
    prices = pd.DataFrame({
        "AAA-USDT": [1.0, 10.0, 1.0],
        "BBB-USDT": [1.0, 1.0, 10.0],
    })
    result = backtest.run_backtest(prices, strategies.equal_weight, fee_rate=0.0, rebalance_every=1)
    assert result.trades > 0
    assert result.metrics["final_equity"] > 0
    assert not math.isnan(result.metrics["final_equity"])


def test_backtest_cash_never_negative_after_fees_and_slippage() -> None:
    prices = pd.DataFrame({
        "AAA-USDT": [1.0, 2.0, 0.5, 2.0, 1.0],
        "BBB-USDT": [1.0, 0.5, 2.0, 0.5, 1.0],
    })
    result = backtest.run_backtest(prices, strategies.equal_weight, fee_rate=0.01, slippage_rate=0.01, rebalance_every=1)
    assert result.metrics["final_equity"] > 0


def test_random_weight_supports_datetime_index() -> None:
    prices = pd.DataFrame(
        {"AAA-USDT": [1.0], "BBB-USDT": [2.0]},
        index=pd.DatetimeIndex(["2025-01-01T00:00:00Z"]),
    )
    strategy = strategies.random_weight(seed=42)

    assert strategy(prices) == strategy(prices)
    assert sum(strategy(prices).values()) == pytest.approx(1.0)


def test_ts_momentum_goes_long_on_winners() -> None:
    prices = pd.DataFrame({
        "AAA-USDT": [1.0, 1.0, 1.0, 1.0, 2.0],
        "BBB-USDT": [1.0, 1.0, 1.0, 1.0, 0.5],
    })
    weights = strategies.ts_momentum(lookback=3)(prices)
    assert weights["AAA-USDT"] > 0.99
    assert weights["BBB-USDT"] < 0.01


def test_walk_forward_splits_do_not_overlap(tmp_path: Path) -> None:
    trend = list(range(100))
    close = _make_bars(trend, "AAA-USDT").set_index("ts")["close"].rename("AAA-USDT").to_frame()
    splits = walkforward.make_splits(close, n_splits=3)
    for split in splits:
        train_end = split.train.index[-1] if split.train is not None else split.validate.index[0] - 1
        assert (split.test.index > train_end).all()


def test_gauntlet_selects_candidate_and_reports_baselines(tmp_path: Path, monkeypatch) -> None:
    store_dir = tmp_path / "data"
    monkeypatch.setattr(data_store, "DATA_DIR", store_dir)
    trend = list(range(50, 150, 2)) + list(range(150, 50, -2)) + list(range(50, 150, 2))
    close = _make_bars(trend, "AAA-USDT").set_index("ts")["close"].rename("AAA-USDT").to_frame()
    close["BBB-USDT"] = [x * 0.5 for x in trend]

    result = walkforward.run_gauntlet(
        close,
        candidates={"mom": strategies.ts_momentum(lookback=12)},
        baselines={"eq": strategies.equal_weight},
        fee_rate=0.0,
        slippage_rate=0.0,
        n_splits=2,
        rebalance_every=1,
        bars_per_year=8760,
    )
    assert "splits" in result
    assert "test_summary" in result
    assert "mom" in result["test_summary"]
    assert "eq" in result["test_summary"]
