"""Custom crypto alpha (v3): regime-gated trend/reversal blend.

Follow-up to custom_crypto_momentum_trend[_v2]: both prior versions had
negative bench IC (the cross-sectional ranking was not predictive), and the
SMA50 trend gate alone did not fix it.

v3 changes the signal itself, not just the gate:

1. Blend: 70% 20-bar trend + 30% inverted 5-bar reversal, each cross-
   sectionally z-scored before combining, so the two legs are commensurable.
2. Regime filter: only keep a symbol's blended score when the magnitude of
   its raw 20-bar trend exceeds its own trailing 60-bar rolling volatility
   (trend.rolling(60).std()) -- i.e. only trade when the move is bigger than
   recent noise. Everything else is masked to NaN and drops out of the
   top-N ranking (research/alpha_adapter.py coerces inf/-inf to NaN and
   drops NaN before ranking, so masking to NaN is the correct mechanism
   here, not -inf).

Position sizing (vol-targeted weights), rebalance buffer bands, and
per-asset trailing stops are NOT part of this alpha -- those are portfolio
construction / execution concerns, not signal concerns, and the current
research.alpha_adapter.alpha_to_strategy always returns equal weight across
the selected top-N. Turnover reduction for this alpha is expected to come
from the CLI's --rebalance-every (e.g. weekly = 168 bars on 1h data), not
from logic in this file.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import ts_std

__alpha_meta__ = {
    'id': 'custom_crypto_trend_reversal_regime',
    'nickname': 'Crypto trend+reversal blend, regime-gated by trend-vs-own-vol',
    'theme': ['momentum', 'reversal'],
    'formula_latex': (
        r'\bigl(0.7\,\mathrm{zscore}_x(r_{20}) - 0.3\,\mathrm{zscore}_x(r_{5})\bigr) '
        r'\text{ where } |r_{20}| > \mathrm{std}_{60}(r_{20})\text{, else NaN}'
    ),
    'columns_required': ['close'],
    'universe': ['crypto'],
    'frequency': ['1h'],
    'decay_horizon': 20,
    'min_warmup_bars': 80,
    'notes': (
        'v3 follow-up to custom_crypto_momentum_trend[_v2] (both had negative bench IC). '
        'Blends 20-bar trend with an inverted 5-bar reversal (each cross-sectionally '
        'z-scored), and masks out any symbol whose raw 20-bar trend does not exceed its '
        'own trailing 60-bar volatility (regime filter -- only trade when the move is '
        'larger than recent noise). Masked entries are NaN, not -inf, matching how '
        'research.alpha_adapter drops non-finite scores before ranking. Does not implement '
        'vol-targeted position sizing, rebalance buffer bands, or trailing stops -- those '
        'are portfolio-construction features the current backtest engine (equal-weight '
        'top-N via alpha_adapter.alpha_to_strategy) does not support; use --rebalance-every '
        'for turnover control instead.'
    ),
}


def _cross_sectional_zscore(df: pd.DataFrame) -> pd.DataFrame:
    """Per-row z-score: (x - row_mean) / row_std; zero/NaN std rows -> NaN."""
    mean = df.mean(axis=1, skipna=True)
    std = df.std(axis=1, ddof=1, skipna=True)
    centered = df.sub(mean, axis=0)
    result = centered.div(std.where(std > 0), axis=0)
    return result.replace([np.inf, -np.inf], np.nan)


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Regime-gated blend of 20-bar trend and inverted 5-bar reversal."""
    close = panel['close']

    trend = close.pct_change(20)
    reversal = -close.pct_change(5)

    trend_z = _cross_sectional_zscore(trend)
    reversal_z = _cross_sectional_zscore(reversal)
    combined = 0.70 * trend_z + 0.30 * reversal_z

    trend_vol = ts_std(trend, 60)
    in_regime = trend.abs() > trend_vol

    return combined.where(in_regime, np.nan)
