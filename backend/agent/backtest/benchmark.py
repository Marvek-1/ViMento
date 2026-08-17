"""Benchmark ticker resolution and fetch for backtest comparison.

This module resolves and fetches benchmark data for a strategy universe.

Doctrine:
- Do not silently erase benchmark failures.
- Return a receipt for every outcome.
- A benchmark result is not evidence unless it is resolved, fetched, valid,
  and aligned to the strategy window.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Any, Optional, Literal

import pandas as pd

from backtest.coverage import coverage_receipt_for_frame
from backtest.loaders.yfinance_loader import DataLoader as YfinanceLoader


BenchmarkStatus = Literal[
    "ok",
    "no_benchmark",
    "resolve_failed",
    "fetch_failed",
    "empty_data",
    "missing_close",
    "insufficient_bars",
    "invalid_returns",
    "coverage_failed",
]

# Crypto benchmarks never touch yfinance: exchange-native BTC-USDT through
# the same coverage-receipt law the strategy symbols use, Binance first
# because it's the queue member proven to deliver full requested windows.
CRYPTO_BENCHMARK_SOURCE_ORDER: list[str] = ["binance", "okx", "bybit", "gate", "ccxt"]


# -------------------------------------------------------------------
# Benchmark map: canonical market type → default economic benchmark
# -------------------------------------------------------------------

MARKET_BENCHMARKS: dict[str, Optional[str]] = {
    "us_equity": "SPY",
    "hk_equity": "03100.HK",
    "a_share": "000300.SS",
    "crypto": "BTC-USD",
    "futures": None,
    "forex": None,
}


# Optional source-specific symbol dialects.
# Economic benchmark and fetch ticker are not always the same string.
SOURCE_BENCHMARK_ALIASES: dict[str, dict[str, str]] = {
    "yfinance": {
        "crypto": "BTC-USD",
        "hk_equity": "03100.HK",
        "a_share": "000300.SS",
        "us_equity": "SPY",
    },
    "binance": {
        "crypto": "BTC-USDT",
    },
    "gate": {
        "crypto": "BTC-USDT",
    },
    "okx": {
        "crypto": "BTC-USDT",
    },
    "bybit": {
        "crypto": "BTC-USDT",
    },
}


@dataclass(frozen=True)
class BenchmarkReceipt:
    status: BenchmarkStatus
    market: str
    requested_source: str
    fetch_source: Optional[str]
    ticker: Optional[str]
    explicit_ticker: Optional[str]
    strategy_codes: list[str]
    start_date: str
    end_date: str
    interval: str
    bars: int = 0
    warnings: list[str] = field(default_factory=list)
    error: Optional[str] = None
    # Same requested-window coverage law the strategy symbols use (see
    # backtest.coverage.coverage_receipt_for_frame) -- a benchmark that
    # fetched successfully but on the wrong window is not comparable.
    coverage_ratio: float = 0.0
    coverage_ok: bool = False
    window_integrity_error: Optional[str] = None


@dataclass(frozen=True)
class BenchmarkResult:
    receipt: BenchmarkReceipt
    ret_series: pd.Series
    total_ret: float

    @property
    def ok(self) -> bool:
        return self.receipt.status == "ok"


def resolve_benchmark(
    strategy_codes: list[str],
    source: str,
    start_date: str,
    end_date: str,
    interval: str = "1D",
    explicit: Optional[str] = None,
    *,
    min_bars: int = 2,
) -> BenchmarkResult:
    """Resolve and fetch the appropriate benchmark.

    Always returns BenchmarkResult with a receipt.

    A failed benchmark returns an empty return series and total_ret=0.0,
    but the receipt status explains why it failed. Callers must not treat
    non-ok statuses as benchmark evidence.
    """
    normalized_source = _normalize_source(source)
    market = _infer_market(strategy_codes, normalized_source)
    ticker = _resolve_ticker(
        market=market,
        source=normalized_source,
        explicit=explicit,
    )

    base_receipt = {
        "market": market,
        "requested_source": source,
        "fetch_source": None,
        "ticker": ticker,
        "explicit_ticker": explicit,
        "strategy_codes": list(strategy_codes),
        "start_date": start_date,
        "end_date": end_date,
        "interval": interval,
    }

    if ticker is None:
        return _empty_result(
            BenchmarkReceipt(
                status="no_benchmark",
                warnings=[f"No benchmark configured for market={market!r}."],
                **base_receipt,
            )
        )

    try:
        if market == "crypto":
            bench_df, fetch_source = _fetch_crypto_benchmark(
                ticker=ticker,
                start_date=start_date,
                end_date=end_date,
                interval=interval,
            )
        else:
            fetch_source = "yfinance"
            bench_df = _fetch_benchmark(
                ticker=ticker,
                start_date=start_date,
                end_date=end_date,
                interval=interval,
            )
    except Exception as exc:
        return _empty_result(
            BenchmarkReceipt(
                status="fetch_failed",
                error=f"{type(exc).__name__}: {exc}",
                **base_receipt,
            )
        )
    base_receipt["fetch_source"] = fetch_source

    if bench_df is None or bench_df.empty:
        return _empty_result(
            BenchmarkReceipt(
                status="empty_data",
                error=f"Benchmark fetch returned no data for ticker={ticker!r}.",
                **base_receipt,
            )
        )

    close_col = _find_close_column(bench_df)
    if close_col is None:
        return _empty_result(
            BenchmarkReceipt(
                status="missing_close",
                bars=int(len(bench_df)),
                error=f"Benchmark data has no close column. Columns={list(bench_df.columns)!r}",
                **base_receipt,
            )
        )

    close = pd.to_numeric(bench_df[close_col], errors="coerce").dropna()

    if len(close) < min_bars:
        return _empty_result(
            BenchmarkReceipt(
                status="insufficient_bars",
                bars=int(len(close)),
                error=f"Benchmark has {len(close)} valid close bars; min_bars={min_bars}.",
                **base_receipt,
            )
        )

    ret_series = close.pct_change().fillna(0.0)

    if not _valid_return_series(ret_series):
        return _empty_result(
            BenchmarkReceipt(
                status="invalid_returns",
                bars=int(len(ret_series)),
                error="Benchmark return series contains non-finite values.",
                **base_receipt,
            )
        )

    total_ret = float((1.0 + ret_series).prod() - 1.0)

    if not isfinite(total_ret):
        return _empty_result(
            BenchmarkReceipt(
                status="invalid_returns",
                bars=int(len(ret_series)),
                error="Benchmark total return is non-finite.",
                **base_receipt,
            )
        )

    # Same requested-window coverage law the strategy symbols use: a fetch
    # that succeeded on the wrong window is not comparable, so status can
    # only be "ok" when coverage_ok is true.
    coverage = coverage_receipt_for_frame(
        bench_df,
        requested_start=start_date,
        requested_end=end_date,
        interval=interval,
    )
    if not coverage["coverage_ok"]:
        return _empty_result(
            BenchmarkReceipt(
                status="coverage_failed",
                bars=int(len(ret_series)),
                error=f"Benchmark window coverage failed: {coverage['window_integrity_error']}",
                coverage_ratio=coverage["coverage_ratio"],
                coverage_ok=False,
                window_integrity_error=coverage["window_integrity_error"],
                **base_receipt,
            )
        )

    receipt = BenchmarkReceipt(
        status="ok",
        bars=int(len(ret_series)),
        coverage_ratio=coverage["coverage_ratio"],
        coverage_ok=True,
        window_integrity_error=coverage["window_integrity_error"],
        **base_receipt,
    )

    return BenchmarkResult(
        receipt=receipt,
        ret_series=ret_series,
        total_ret=total_ret,
    )


# -------------------------------------------------------------------
# Internal helpers
# -------------------------------------------------------------------

def _resolve_ticker(
    *,
    market: str,
    source: str,
    explicit: Optional[str],
) -> Optional[str]:
    """Pick benchmark ticker for the fetch dialect."""
    if explicit:
        return explicit

    # Crypto always benchmarks against the exchange-native BTC-USDT pair,
    # regardless of the strategy's requested source -- there is no yfinance
    # fallback here (BTC-USD via yfinance is a different, non-comparable
    # instrument, and yfinance is not in the crypto fetch queue at all; see
    # _fetch_crypto_benchmark / CRYPTO_BENCHMARK_SOURCE_ORDER).
    if market == "crypto":
        return "BTC-USDT"

    source_aliases = SOURCE_BENCHMARK_ALIASES.get(source, {})
    if market in source_aliases:
        return source_aliases[market]

    yfinance_aliases = SOURCE_BENCHMARK_ALIASES.get("yfinance", {})
    if market in yfinance_aliases:
        return yfinance_aliases[market]

    return MARKET_BENCHMARKS.get(market)


def _infer_market(codes: list[str], source: str) -> str:
    """Infer market from strategy codes and source.

    Delegates to the same ``_detect_market`` symbol classifier that
    ``runner.py``/``composite.py`` use for engine routing, so the benchmark
    reflects the market the strategy is actually judged to be trading in
    instead of a separately maintained heuristic that can drift out of sync
    (a previous version of this function had no forex-detecting branch at
    all, so forex strategies were silently benchmarked against SPY).

    An explicit crypto-exchange source always wins over code-pattern
    detection, since exchange-native codes (e.g. ``BTC-USD``) don't always
    match the stricter ``-USDT``/``/USDT`` patterns ``_detect_market`` uses.
    """
    from backtest.engines._market_hooks import _detect_market

    normalized_source = _normalize_source(source)
    if normalized_source in {"okx", "ccxt", "binance", "bybit", "gate"}:
        return "crypto"

    normalized_codes = [code.strip() for code in codes if code and code.strip()]
    if not normalized_codes:
        return "us_equity"

    markets = [_detect_market(code) for code in normalized_codes]
    # _detect_market's "a_share" is also its no-pattern-matched fallback, so
    # prefer the first market that was actually recognized by a pattern;
    # only fall back to a_share when that's genuinely all we saw.
    for market in markets:
        if market != "a_share":
            return market
    return markets[0]


def _fetch_benchmark(
    ticker: str,
    start_date: str,
    end_date: str,
    interval: str,
) -> pd.DataFrame:
    """Fetch benchmark OHLCV data via yfinance.

    Passes ``interval`` through unmodified: ``YfinanceLoader.fetch`` owns its
    own project-interval-to-yfinance-interval mapping (including special
    cases like ``4H`` -> ``1h`` where yfinance has no native bar), so
    normalizing it here first would bypass that and send yfinance a dialect
    string it doesn't actually support.
    """
    loader = YfinanceLoader()
    result = loader.fetch([ticker], start_date, end_date, interval=interval)

    if isinstance(result, dict):
        df = result.get(ticker)
    elif isinstance(result, pd.DataFrame):
        df = result
    else:
        return pd.DataFrame()

    if not isinstance(df, pd.DataFrame):
        return pd.DataFrame()

    return df


def _fetch_crypto_benchmark(
    ticker: str,
    start_date: str,
    end_date: str,
    interval: str,
) -> tuple[pd.DataFrame, Optional[str]]:
    """Fetch a crypto benchmark through the Binance-first exchange loader queue.

    Never touches yfinance: BTC-USD via yfinance is a different, non-comparable
    instrument from the exchange-native BTC-USDT pair the strategy trades.

    Returns:
        ``(dataframe, source_name)`` for the first loader that returned data;
        ``(empty_dataframe, None)`` if every loader in the queue failed or was
        unavailable.
    """
    from backtest.loaders.registry import LOADER_REGISTRY

    last_error: Exception | None = None
    for name in CRYPTO_BENCHMARK_SOURCE_ORDER:
        loader_cls = LOADER_REGISTRY.get(name)
        if loader_cls is None:
            continue
        try:
            loader = loader_cls()
            if not loader.is_available():
                continue
            result = loader.fetch([ticker], start_date, end_date, interval=interval)
        except Exception as exc:  # noqa: BLE001 - try the next source in the queue
            last_error = exc
            continue

        if isinstance(result, dict):
            df = result.get(ticker)
        elif isinstance(result, pd.DataFrame):
            df = result
        else:
            df = None

        if isinstance(df, pd.DataFrame) and not df.empty:
            return df, name

    if last_error is not None:
        raise last_error
    return pd.DataFrame(), None


def _find_close_column(df: pd.DataFrame) -> Optional[str]:
    """Find close column regardless of common capitalization."""
    for candidate in ("close", "Close", "adj_close", "Adj Close", "adjclose"):
        if candidate in df.columns:
            return candidate
    return None


def _normalize_source(source: str) -> str:
    return (source or "auto").strip().lower()


def _valid_return_series(series: pd.Series) -> bool:
    if series.empty:
        return False
    finite_mask = pd.notna(series)
    if not finite_mask.all():
        return False
    return bool(pd.Series(series).map(lambda x: isfinite(float(x))).all())


def _empty_result(receipt: BenchmarkReceipt) -> BenchmarkResult:
    return BenchmarkResult(
        receipt=receipt,
        ret_series=pd.Series(dtype=float),
        total_ret=0.0,
    )