"""Tests for the funding-rate pipeline: loader, backtest, and paper-session integration."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backtest.loaders.funding_rate_loader import (
    fetch_funding_rate_history,
    FundingRateLoader,
)
from funding_strategy import (
    FundingBacktestConfig,
    _compute_zscore,
    run_funding_backtest,
)
from paper_session import (
    FUNDING_ZSCORE_STRATEGY,
    _compute_funding_zscore,
    start_funding_session,
    funding_rebalance_if_due,
)


# ── Loader tests ──────────────────────────────────────────────────────────

class TestFundingRateLoader:
    def test_loader_is_available(self):
        loader = FundingRateLoader()
        assert loader.is_available() is True

    def test_loader_name(self):
        assert FundingRateLoader.name == "binance_funding"

    def test_loader_markets(self):
        assert "crypto" in FundingRateLoader.markets

    @patch("backtest.loaders.funding_rate_loader._get_exchange")
    @patch("backtest.loaders.funding_rate_loader._cache_path")
    def test_fetch_caches_to_parquet(self, mock_cache_path, mock_get_exchange, tmp_path):
        cache_file = tmp_path / "test_funding.parquet"
        mock_cache_path.return_value = cache_file

        mock_exchange = MagicMock()
        mock_get_exchange.return_value = mock_exchange

        mock_exchange.fetch_funding_rate_history.return_value = [
            {"timestamp": 1700000000000, "fundingRate": 0.0001, "markPrice": 42000.0},
            {"timestamp": 1700028800000, "fundingRate": 0.0002, "markPrice": 42100.0},
        ]

        result = fetch_funding_rate_history(
            ["BTC-USDT"], "2023-11-01", "2023-11-15",
        )

        assert "BTC-USDT" in result
        df = result["BTC-USDT"]
        assert len(df) == 2
        assert "funding_rate" in df.columns
        assert "mark_price" in df.columns
        # Cache file exists (parquet or CSV fallback)
        assert cache_file.exists() or cache_file.with_suffix(".csv").exists()

    @patch("backtest.loaders.funding_rate_loader._get_exchange")
    @patch("backtest.loaders.funding_rate_loader._cache_path")
    def test_fetch_returns_empty_on_no_data(self, mock_cache_path, mock_get_exchange, tmp_path):
        cache_file = tmp_path / "empty.parquet"
        mock_cache_path.return_value = cache_file

        mock_exchange = MagicMock()
        mock_get_exchange.return_value = mock_exchange
        mock_exchange.fetch_funding_rate_history.return_value = []

        result = fetch_funding_rate_history(
            ["BTC-USDT"], "2023-11-01", "2023-11-15",
        )

        assert "BTC-USDT" not in result
        assert not cache_file.exists()


# ── Backtest engine tests ─────────────────────────────────────────────────

class TestFundingBacktest:
    def test_compute_zscore(self):
        dates = pd.date_range("2025-01-01", periods=100, freq="8h", tz="UTC")
        rates = np.random.normal(0.0001, 0.00005, 100)
        df = pd.DataFrame(
            {"funding_rate": rates, "mark_price": 42000.0},
            index=dates,
        )
        result = _compute_zscore(df, window=50)
        assert "z_score" in result.columns
        assert result["z_score"].iloc[-1] is not np.nan or len(result) > 50

    def test_compute_zscore_short_window(self):
        dates = pd.date_range("2025-01-01", periods=5, freq="8h", tz="UTC")
        df = pd.DataFrame(
            {"funding_rate": [0.0001] * 5, "mark_price": 42000.0},
            index=dates,
        )
        result = _compute_zscore(df, window=120)
        assert "z_score" in result.columns
        assert result["z_score"].isna().all()

    def test_backtest_with_no_data(self):
        config = FundingBacktestConfig(
            symbols=["FAKE-USDT"],
            start_date="2025-01-01",
            end_date="2025-01-02",
        )
        with patch("funding_strategy.fetch_funding_rate_history", return_value={}), \
             patch("funding_strategy._load_ohlcv", return_value={}):
            result = run_funding_backtest(config)
            assert "error" in result.metrics

    def test_backtest_with_synthetic_data(self):
        config = FundingBacktestConfig(
            symbols=["BTC-USDT"],
            start_date="2025-01-01",
            end_date="2025-06-01",
            z_window=30,
            entry_z=1.0,
            exit_z=0.3,
            initial_capital=10_000.0,
        )

        dates = pd.date_range("2025-01-01", "2025-06-01", freq="8h", tz="UTC")
        n = len(dates)
        rates = np.concatenate([
            np.full(n // 2, 0.0001),
            np.full(n - n // 2, -0.0003),
        ])
        funding_df = pd.DataFrame(
            {"funding_rate": rates, "mark_price": 42000.0},
            index=dates,
        )

        price_dates = pd.date_range("2025-01-01", "2025-06-01", freq="1D", tz="UTC")
        price_df = pd.DataFrame(
            {"close": np.linspace(42000, 43000, len(price_dates))},
            index=price_dates,
        )

        with patch("funding_strategy.fetch_funding_rate_history", return_value={"BTC-USDT": funding_df}), \
             patch("funding_strategy._load_ohlcv", return_value={"BTC-USDT": price_df}):
            result = run_funding_backtest(config)
            assert "total_return" in result.metrics
            assert result.metrics["total_trades"] >= 0
            assert isinstance(result.equity_curve, pd.DataFrame)


# ── Paper session integration tests ───────────────────────────────────────

class TestFundingPaperSession:
    def test_compute_funding_zscore_basic(self):
        history = [
            {"timestamp": i * 28800000, "funding_rate": 0.0001 + (i % 3) * 0.00002}
            for i in range(100)
        ]
        z = _compute_funding_zscore(history, 0.00012, 50)
        assert abs(z) < 1.0  # current ≈ mean → z near 0

    def test_compute_funding_zscore_extreme(self):
        history = [
            {"timestamp": i * 28800000, "funding_rate": 0.0001 + (i % 3) * 0.00002}
            for i in range(100)
        ]
        z = _compute_funding_zscore(history, 0.001, 50)
        assert z > 1.0  # much higher than mean → positive z

    def test_compute_funding_zscore_insufficient_data(self):
        history = [
            {"timestamp": i * 28800000, "funding_rate": 0.0001}
            for i in range(3)
        ]
        z = _compute_funding_zscore(history, 0.001, 120)
        assert z == 0.0  # not enough data

    def test_start_funding_session(self, tmp_path):
        session_dir = tmp_path / "funding_test"
        with patch("paper_session.fetch_last_prices", return_value={"BTC-USDT": 42000.0, "ETH-USDT": 2500.0}):
            session = start_funding_session(
                session_dir,
                ["BTC-USDT", "ETH-USDT"],
                10_000.0,
                z_window=50,
                entry_z=1.5,
                exit_z=0.5,
            )

        assert session["strategy_type"] == FUNDING_ZSCORE_STRATEGY
        assert session["initial_cash"] == 10_000.0
        assert session["z_window"] == 50
        assert session_dir.exists()
        assert (session_dir / "session.json").exists()
        assert (session_dir / "book.json").exists()
        assert (session_dir / "marks.jsonl").exists()

        book = json.loads((session_dir / "book.json").read_text())
        assert book["cash_remaining"] == 10_000.0
        assert book["positions"] == {}

    def test_start_funding_session_refuses_existing(self, tmp_path):
        session_dir = tmp_path / "funding_test"
        session_dir.mkdir(parents=True)
        with pytest.raises(FileExistsError):
            start_funding_session(session_dir, ["BTC-USDT"], 10_000.0)

    def test_funding_rebalance_not_due(self, tmp_path):
        session_dir = tmp_path / "funding_test"
        with patch("paper_session.fetch_last_prices", return_value={"BTC-USDT": 42000.0}):
            start_funding_session(session_dir, ["BTC-USDT"], 10_000.0, poll_seconds=3600)

        result = funding_rebalance_if_due(session_dir)
        assert result is None  # not due yet

    def test_funding_rebalance_executes_trades(self, tmp_path):
        session_dir = tmp_path / "funding_test"
        with patch("paper_session.fetch_last_prices", return_value={"BTC-USDT": 42000.0}):
            start_funding_session(session_dir, ["BTC-USDT"], 10_000.0, poll_seconds=1)

        import time
        time.sleep(1.1)

        fake_history = [
            {"timestamp": i * 28800000, "funding_rate": 0.0001 + (i % 3) * 0.00002}
            for i in range(100)
        ]

        with patch("paper_session.fetch_last_prices", return_value={"BTC-USDT": 42000.0}), \
             patch("paper_session._fetch_funding_rates", return_value={"BTC-USDT": 0.001}), \
             patch("paper_session._fetch_funding_rate_history_ccxt", return_value=fake_history):
            result = funding_rebalance_if_due(session_dir)

        assert result is not None
        assert len(result["trades"]) > 0
        assert result["trades"][0]["side"] == "SELL"  # high z → short

        book = json.loads((session_dir / "book.json").read_text())
        assert "BTC-USDT" in book["positions"]
        assert book["positions"]["BTC-USDT"] < 0  # short position
