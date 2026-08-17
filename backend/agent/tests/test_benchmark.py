"""Tests for backtest.benchmark: every outcome must be a receipt, not a silence."""

from __future__ import annotations

import pandas as pd
import pytest

from backtest.benchmark import (
    BenchmarkResult,
    resolve_benchmark,
)
from backtest.loaders.binance_loader import DataLoader as BinanceLoader
from backtest.loaders.yfinance_loader import DataLoader as YfinanceLoader


def _bars(closes: list[float], start: str = "2024-01-01") -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "volume": [1000] * len(closes),
        },
        index=dates,
    )


def test_resolve_benchmark_never_returns_none():
    """The whole point of the receipt model: no silent None on any path."""
    result = resolve_benchmark(
        strategy_codes=["EURUSD"],
        source="forex",
        start_date="2024-01-01",
        end_date="2024-03-31",
    )
    assert result is not None
    assert isinstance(result, BenchmarkResult)


def test_no_benchmark_for_unmapped_market_returns_receipt():
    # futures maps to MARKET_BENCHMARKS["futures"] = None.
    result = resolve_benchmark(
        strategy_codes=["IF2403"],
        source="tushare",
        start_date="2024-01-01",
        end_date="2024-03-31",
    )
    assert result.receipt.market == "futures"
    assert result.receipt.status == "no_benchmark"
    assert result.ok is False
    assert result.total_ret == 0.0


def test_forex_infers_forex_market_and_returns_no_benchmark():
    """Regression: forex must not silently fall through to us_equity/SPY.

    _infer_market previously reimplemented its own symbol classifier with no
    forex branch at all, so any forex strategy got benchmarked against SPY.
    It now delegates to the shared _detect_market classifier used by
    runner.py/composite.py for engine routing.
    """
    result = resolve_benchmark(
        strategy_codes=["EUR/USD"],
        source="yfinance",
        start_date="2024-01-01",
        end_date="2024-03-31",
    )
    assert result.receipt.market == "forex"
    assert result.receipt.status == "no_benchmark"
    assert result.receipt.ticker is None
    assert result.ok is False


def test_forex_dotfx_symbol_also_infers_forex_market():
    result = resolve_benchmark(
        strategy_codes=["EURUSD.FX"],
        source="yfinance",
        start_date="2024-01-01",
        end_date="2024-03-31",
    )
    assert result.receipt.market == "forex"
    assert result.receipt.status == "no_benchmark"


def test_crypto_benchmark_resolves_dialect_specific_ticker():
    result = resolve_benchmark(
        strategy_codes=["BTC-USDT", "ETH-USDT"],
        source="binance",
        start_date="2024-01-01",
        end_date="2024-03-31",
    )
    assert result.receipt.market == "crypto"
    assert result.receipt.ticker == "BTC-USDT"


def test_explicit_ticker_overrides_resolution():
    result = resolve_benchmark(
        strategy_codes=["BTC-USDT"],
        source="binance",
        start_date="2024-01-01",
        end_date="2024-03-31",
        explicit="ETH-USD",
    )
    assert result.receipt.ticker == "ETH-USD"
    assert result.receipt.explicit_ticker == "ETH-USD"


def test_failed_fetch_is_visible_not_silent(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("backtest.benchmark.CRYPTO_BENCHMARK_SOURCE_ORDER", ["binance"])

    def boom(self, codes, start_date, end_date, fields=None, interval="1D"):
        raise RuntimeError("fetch exploded")

    monkeypatch.setattr(BinanceLoader, "fetch", boom)

    result = resolve_benchmark(
        strategy_codes=["BTC-USDT"],
        source="binance",
        start_date="2024-01-01",
        end_date="2024-03-31",
    )

    assert result.receipt.status == "fetch_failed"
    assert "fetch exploded" in result.receipt.error
    assert result.ok is False


def test_missing_close_is_visible(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("backtest.benchmark.CRYPTO_BENCHMARK_SOURCE_ORDER", ["binance"])

    def fake_fetch(self, codes, start_date, end_date, fields=None, interval="1D"):
        return {codes[0]: pd.DataFrame({"open": [1, 2, 3]})}

    monkeypatch.setattr(BinanceLoader, "fetch", fake_fetch)

    result = resolve_benchmark(
        strategy_codes=["BTC-USDT"],
        source="binance",
        start_date="2024-01-01",
        end_date="2024-03-31",
    )

    assert result.receipt.status == "missing_close"


def test_empty_fetch_result_is_visible(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("backtest.benchmark.CRYPTO_BENCHMARK_SOURCE_ORDER", ["binance"])

    def fake_fetch(self, codes, start_date, end_date, fields=None, interval="1D"):
        return {}

    monkeypatch.setattr(BinanceLoader, "fetch", fake_fetch)

    result = resolve_benchmark(
        strategy_codes=["BTC-USDT"],
        source="binance",
        start_date="2024-01-01",
        end_date="2024-03-31",
    )

    assert result.receipt.status == "empty_data"


def test_insufficient_bars_is_visible(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("backtest.benchmark.CRYPTO_BENCHMARK_SOURCE_ORDER", ["binance"])

    def fake_fetch(self, codes, start_date, end_date, fields=None, interval="1D"):
        return {codes[0]: _bars([100.0])}

    monkeypatch.setattr(BinanceLoader, "fetch", fake_fetch)

    result = resolve_benchmark(
        strategy_codes=["BTC-USDT"],
        source="binance",
        start_date="2024-01-01",
        end_date="2024-03-31",
        min_bars=2,
    )

    assert result.receipt.status == "insufficient_bars"


def test_successful_fetch_computes_receipt_and_returns(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("backtest.benchmark.CRYPTO_BENCHMARK_SOURCE_ORDER", ["binance"])

    def fake_fetch(self, codes, start_date, end_date, fields=None, interval="1D"):
        return {codes[0]: _bars([100.0, 110.0, 121.0])}

    monkeypatch.setattr(BinanceLoader, "fetch", fake_fetch)

    # end_date matches the 3 delivered bars so the requested-window coverage
    # receipt passes (coverage_ok=True) -- status can only be "ok" otherwise.
    result = resolve_benchmark(
        strategy_codes=["BTC-USDT"],
        source="binance",
        start_date="2024-01-01",
        end_date="2024-01-03",
    )

    assert result.receipt.status == "ok"
    assert result.ok is True
    assert result.receipt.bars == 3
    assert result.receipt.fetch_source == "binance"
    assert result.receipt.coverage_ok is True
    assert result.total_ret == pytest.approx(0.21)


def test_raw_interval_is_passed_through_to_loader_unmodified(monkeypatch: pytest.MonkeyPatch):
    """benchmark.py must not second-guess the loader's own interval dialect mapping."""
    monkeypatch.setattr("backtest.benchmark.CRYPTO_BENCHMARK_SOURCE_ORDER", ["binance"])
    captured: dict[str, object] = {}

    def fake_fetch(self, codes, start_date, end_date, fields=None, interval="1D"):
        captured["interval"] = interval
        return {codes[0]: _bars([100.0, 101.0])}

    monkeypatch.setattr(BinanceLoader, "fetch", fake_fetch)

    resolve_benchmark(
        strategy_codes=["BTC-USDT"],
        source="binance",
        start_date="2024-01-01",
        end_date="2024-03-31",
        interval="4H",
    )

    assert captured["interval"] == "4H"


def test_crypto_benchmark_never_uses_yfinance(monkeypatch: pytest.MonkeyPatch):
    """Doctrine: no Yahoo crypto benchmark, ever -- not even as a fallback."""
    monkeypatch.setattr("backtest.benchmark.CRYPTO_BENCHMARK_SOURCE_ORDER", ["binance"])

    def fake_binance_fetch(self, codes, start_date, end_date, fields=None, interval="1D"):
        return {codes[0]: _bars([100.0, 110.0, 121.0])}

    def yfinance_should_never_be_called(self, codes, start_date, end_date, fields=None, interval="1D"):
        raise AssertionError("yfinance must never be used for a crypto benchmark")

    monkeypatch.setattr(BinanceLoader, "fetch", fake_binance_fetch)
    monkeypatch.setattr(YfinanceLoader, "fetch", yfinance_should_never_be_called)

    result = resolve_benchmark(
        strategy_codes=["BTC-USDT"],
        source="binance",
        start_date="2024-01-01",
        end_date="2024-01-03",
    )

    assert result.receipt.status == "ok"
    assert result.receipt.fetch_source == "binance"
    assert result.receipt.ticker == "BTC-USDT"


def test_crypto_benchmark_coverage_gate_rejects_truncated_window(monkeypatch: pytest.MonkeyPatch):
    """A benchmark that fetched successfully on the wrong window is not comparable."""
    monkeypatch.setattr("backtest.benchmark.CRYPTO_BENCHMARK_SOURCE_ORDER", ["binance"])

    def truncated_fetch(self, codes, start_date, end_date, fields=None, interval="1D"):
        # Only 3 bars delivered against a ~90-day requested window.
        return {codes[0]: _bars([100.0, 110.0, 121.0])}

    monkeypatch.setattr(BinanceLoader, "fetch", truncated_fetch)

    result = resolve_benchmark(
        strategy_codes=["BTC-USDT"],
        source="binance",
        start_date="2024-01-01",
        end_date="2024-03-31",
    )

    assert result.receipt.status == "coverage_failed"
    assert result.ok is False
    assert result.receipt.coverage_ok is False
    assert result.total_ret == 0.0


def test_benchmark_result_has_no_flat_ticker_attribute():
    """Regression guard: callers must use receipt.ticker, not a flat .ticker.

    A previous version of engines/base.py accessed bench_result.ticker
    directly and crashed with AttributeError once resolve_benchmark started
    returning a receipt-shaped BenchmarkResult on every path. This pins the
    contract so that mistake can't silently reappear.
    """
    result = resolve_benchmark(
        strategy_codes=["IF2403"],
        source="tushare",
        start_date="2024-01-01",
        end_date="2024-03-31",
    )
    assert not hasattr(result, "ticker")
    assert result.receipt.ticker is None
