"""Binance perpetual funding-rate history loader via CCXT.

Fetches historical funding rates for USDT-margined perpetual contracts from
Binance using CCXT's ``fetchFundingRateHistory``.  Stores results as parquet
under the same cache directory used by the OHLCV loaders so a full cache hit
never hits the network.

Schema (one row per funding interval, typically 8h):
    timestamp    – settlement timestamp (UTC, tz-aware)
    symbol       – e.g. ``BTC-USDT``
    funding_rate – decimal rate (e.g. 0.0001 = 0.01 %)
    mark_price   – mark price at settlement (when available)
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from backtest.loaders.base import (
    check_budget,
    positive_env_float,
    positive_env_int,
    retry_with_budget,
    validate_date_range,
)
from backtest.loaders.registry import register

logger = logging.getLogger(__name__)

_CCXT_TIMEOUT_MS = positive_env_int("CCXT_TIMEOUT_MS", 15_000)
_CCXT_FETCH_BUDGET_S = positive_env_float("CCXT_FETCH_BUDGET_S", 120.0)

_CACHE_DIR = Path(
    os.getenv(
        "VIBE_DATA_CACHE_DIR",
        str(Path.home() / ".vibe-trading" / "cache"),
    )
)


def _first_proxy_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def _ccxt_proxy_config() -> dict[str, str]:
    all_proxy = _first_proxy_env("ALL_PROXY", "all_proxy")
    http_proxy = _first_proxy_env("HTTP_PROXY", "http_proxy") or all_proxy
    https_proxy = _first_proxy_env("HTTPS_PROXY", "https_proxy") or all_proxy or http_proxy
    proxies: dict[str, str] = {}
    if http_proxy:
        proxies["http"] = http_proxy
    if https_proxy:
        proxies["https"] = https_proxy
    return proxies


def _get_exchange():
    import ccxt

    config: dict[str, object] = {"enableRateLimit": True, "timeout": _CCXT_TIMEOUT_MS}
    proxies = _ccxt_proxy_config()
    if proxies:
        config["proxies"] = proxies
    return ccxt.binanceusdm(config)


def _ccxt_symbol(code: str) -> str:
    return code.replace("-", "/").upper()


def _cache_path(symbol: str, start_date: str, end_date: str) -> Path:
    safe = symbol.replace("/", "_").replace("-", "_")
    return _CACHE_DIR / "funding_rates" / f"{safe}_{start_date}_{end_date}.parquet"


def fetch_funding_rate_history(
    symbols: List[str],
    start_date: str,
    end_date: str,
    *,
    exchange=None,
) -> Dict[str, pd.DataFrame]:
    """Fetch funding-rate history for one or more perpetual symbols.

    Args:
        symbols: List of symbols like ``["BTC-USDT", "ETH-USDT"]``.
        start_date: Start date (YYYY-MM-DD).
        end_date: End date (YYYY-MM-DD).
        exchange: Optional pre-built ccxt exchange instance.

    Returns:
        Mapping symbol -> DataFrame with columns
        ``[timestamp, funding_rate, mark_price]`` indexed by ``timestamp``.
    """
    validate_date_range(start_date, end_date)

    since_ms = int(pd.Timestamp(start_date).timestamp() * 1000)
    end_ms = int((pd.Timestamp(end_date) + pd.Timedelta(days=1)).timestamp() * 1000)

    own_exchange = exchange is None
    if own_exchange:
        exchange = _get_exchange()

    result: Dict[str, pd.DataFrame] = {}
    try:
        for code in symbols:
            cache_p = _cache_path(code, start_date, end_date)
            if cache_p.exists():
                df = pd.read_parquet(cache_p)
                if not df.empty:
                    result[code] = df
                    continue
            csv_cache = cache_p.with_suffix(".csv")
            if csv_cache.exists():
                df = pd.read_csv(csv_cache, index_col=0, parse_dates=True)
                if not df.empty:
                    result[code] = df
                    continue

            ccxt_sym = _ccxt_symbol(code)
            df = _fetch_one_funding(exchange, ccxt_sym, since_ms, end_ms)
            if df is not None and not df.empty:
                cache_p.parent.mkdir(parents=True, exist_ok=True)
                try:
                    df.to_parquet(cache_p)
                except ImportError:
                    df.to_csv(cache_p.with_suffix(".csv"))
                result[code] = df
            else:
                logger.warning("No funding-rate data for %s (%s to %s)", code, start_date, end_date)
    finally:
        if own_exchange:
            try:
                exchange.close()
            except Exception:
                pass

    return result


def _fetch_one_funding(
    exchange,
    symbol: str,
    since_ms: int,
    end_ms: int,
) -> Optional[pd.DataFrame]:
    """Paginated funding-rate fetch for one symbol."""
    import ccxt

    all_rows: list = []
    cursor = since_ms
    limit = 1000
    deadline = time.monotonic() + _CCXT_FETCH_BUDGET_S
    label = f"funding-rate fetch for {symbol}"

    for _ in range(200):
        check_budget(deadline, label, budget_s=_CCXT_FETCH_BUDGET_S)
        try:
            raw = retry_with_budget(
                lambda: exchange.fetch_funding_rate_history(
                    symbol, since=cursor, limit=limit,
                ),
                transient=ccxt.NetworkError,
                deadline=deadline,
                label=label,
            )
        except AttributeError:
            # Fallback for ccxt versions that spell it differently.
            raw = retry_with_budget(
                lambda: exchange.fetch_funding_history(
                    symbol, since=cursor, limit=limit,
                ),
                transient=ccxt.NetworkError,
                deadline=deadline,
                label=label,
            )

        if not raw:
            break

        all_rows.extend(raw)
        last_ts = raw[-1].get("timestamp", 0)
        if last_ts >= end_ms or len(raw) < limit:
            break
        cursor = last_ts + 1

    if not all_rows:
        return None

    records = []
    for r in all_rows:
        ts = r.get("timestamp")
        if ts is None:
            continue
        if ts >= end_ms:
            break
        records.append({
            "timestamp": pd.Timestamp(ts, unit="ms", tz="UTC"),
            "funding_rate": float(r.get("fundingRate", 0.0)),
            "mark_price": float(r.get("markPrice", 0.0)) if r.get("markPrice") else None,
        })

    if not records:
        return None

    df = pd.DataFrame(records).set_index("timestamp").sort_index()
    df = df[df.index < pd.Timestamp(end_ms, unit="ms", tz="UTC")]
    return df if not df.empty else None


@register
class FundingRateLoader:
    """Registered loader for funding-rate data (not OHLCV)."""

    name = "binance_funding"
    markets = {"crypto"}
    requires_auth = False

    def is_available(self) -> bool:
        try:
            import ccxt  # noqa: F401
            return True
        except ImportError:
            return False

    def __init__(self) -> None:
        pass

    def fetch(
        self,
        codes: List[str],
        start_date: str,
        end_date: str,
        *,
        interval: str = "8H",
        fields: Optional[List[str]] = None,
    ) -> Dict[str, pd.DataFrame]:
        return fetch_funding_rate_history(codes, start_date, end_date)
