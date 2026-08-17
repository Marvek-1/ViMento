"""Custom crypto-native momentum-trend alpha.

Encodes the manual logic behind ``top_gainers_filtered`` /
``pullback_oversold`` as a single formula: 24-bar (24h on 1h bars) momentum,
gated by a 50-bar SMA trend filter, scaled by 14-bar ATR to favor
high-conviction moves relative to recent volatility.

score = (close.pct_change(24) / atr(14)) * (close > sma(50))
"""
from __future__ import annotations

import pandas as pd

from src.factors.base import safe_div, ts_mean

__alpha_meta__ = {
    'id': 'custom_crypto_momentum_trend',
    'nickname': 'Crypto momentum-trend (24h momentum / ATR14, SMA50 trend gate)',
    'theme': ['momentum'],
    'formula_latex': r'\frac{\mathrm{close}_t/\mathrm{close}_{t-24} - 1}{\mathrm{ATR}_{14}} \cdot \mathbb{1}[\mathrm{close}_t > \mathrm{SMA}_{50}]',
    'columns_required': ['high', 'low', 'close'],
    'universe': ['crypto'],
    'frequency': ['1h'],
    'decay_horizon': 24,
    'min_warmup_bars': 50,
    'notes': (
        'Crypto-native momentum: 24-bar return divided by 14-bar ATR (volatility-adjusted '
        'conviction), zeroed out when close is below its 50-bar SMA (trend filter). No '
        'cross-sectional z-score wrapper — the zoo gauntlet ranks raw scores directly to '
        'pick the top-N per rebalance.'
    ),
}


def _atr(high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame, n: int) -> pd.DataFrame:
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        keys=["hl", "hc", "lc"],
    ).groupby(level=1).max()
    return ts_mean(tr, n)


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """24h momentum / ATR(14), gated by close > SMA(50)."""
    high = panel['high']
    low = panel['low']
    close = panel['close']

    momentum = safe_div(close, close.shift(24)) - 1.0
    atr14 = _atr(high, low, close, 14)
    sma50 = ts_mean(close, 50)
    trend_mask = (close > sma50).astype(float)

    return safe_div(momentum, atr14) * trend_mask
