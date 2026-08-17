"""Canonical market-to-source mapping for generated backtest configs."""

from __future__ import annotations

MARKET_TO_SOURCE: dict[str, str] = {
    "a_share": "binance",
    "us_equity": "yfinance",
    "hk_equity": "yfinance",
    "crypto": "bybit",
    "futures": "binance",
    "fund": "cmc",
    "macro": "akshare",
    "forex": "akshare",
}

CANONICAL_SOURCES: frozenset[str] = frozenset(MARKET_TO_SOURCE.values())
CRYPTO_SOURCES: frozenset[str] = frozenset({"binance", "bybit", "gate", "okx", "ccxt"})
