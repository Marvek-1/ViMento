"""Custom crypto-native trend-strength alpha (v2).

Follow-up to ``custom_crypto_momentum_trend``: the ATR(14) denominator in v1
amplified noise during low-volatility consolidations (tiny ATR -> huge score
spikes), driving ~12x the turnover of equal-weight for a negative edge.

v2 drops the ATR scaling entirely and ranks on normalized distance from the
50-bar trend, gated to zero below the trend. No division by a volatile
quantity, so score magnitude only reflects trend strength, not the inverse of
recent volatility. It only changes materially when price moves relative to
its own moving average, not on every noisy high/low print.

score = (close / SMA(50) - 1) * trend_mask
"""
from __future__ import annotations

import pandas as pd

from src.factors.base import safe_div, ts_mean

__alpha_meta__ = {
    'id': 'custom_crypto_momentum_trend_v2',
    'nickname': 'Crypto trend strength v2 (close/SMA50 - 1, SMA50 trend gate)',
    'theme': ['momentum'],
    'formula_latex': r'\left(\frac{\mathrm{close}_t}{\mathrm{SMA}_{50}} - 1\right) \cdot \mathbb{1}[\mathrm{close}_t > \mathrm{SMA}_{50}]',
    'columns_required': ['close'],
    'universe': ['crypto'],
    'frequency': ['1h'],
    'decay_horizon': 50,
    'min_warmup_bars': 50,
    'notes': (
        'v2 follow-up to custom_crypto_momentum_trend: removes the ATR(14) denominator '
        'that amplified noise during low-volatility consolidations. Ranks on normalized '
        'distance above the 50-bar SMA, zeroed out below it. No cross-sectional z-score '
        'wrapper — the zoo gauntlet ranks raw scores directly to pick the top-N per '
        'rebalance.'
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Normalized distance above 50-bar SMA, gated by close > SMA(50)."""
    close = panel['close']
    sma50 = ts_mean(close, 50)
    trend_strength = safe_div(close, sma50) - 1.0
    trend_mask = (close > sma50).astype(float)
    return trend_strength * trend_mask
