"""Binance crypto OHLCV loader via CCXT."""

from __future__ import annotations

from backtest.loaders.ccxt_loader import _CCXTBaseLoader
from backtest.loaders.registry import register


@register
class DataLoader(_CCXTBaseLoader):
    """Binance crypto OHLCV loader, independent of ``CCXT_EXCHANGE``."""

    name = "binance"
    exchange_id = "binance"
