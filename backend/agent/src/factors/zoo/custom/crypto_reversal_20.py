"""Custom crypto alpha (v4): pure 20-bar reversal, no blend, no gate.

Diagnostic finding that motivated this: a symbol-sliced IC check of the raw
20-bar momentum signal (used in v1-v3) against 5-bar forward returns showed
27 of 28 binance_perps_34 symbols with NEGATIVE IC, majors leading
(BTC -0.090, BNB -0.082, SOL -0.057, ETH -0.033), all-symbol mean -0.039.
This is a structural hypothesis change (momentum -> reversal), not a
parameter search: same lookback (20), same top-N (8), same rebalance
cadence, same everything as v2 -- only the sign flips.

score = -(close.pct_change(20))

No cross-sectional z-score wrapper, no volatility/regime gate, no blend --
deliberately identical framework to custom_crypto_momentum_trend_v2 except
for the sign, so any change in gauntlet outcome is attributable to the
reversal hypothesis alone.
"""
from __future__ import annotations

import pandas as pd

__alpha_meta__ = {
    'id': 'custom_crypto_reversal_20',
    'nickname': 'Crypto pure reversal (20-bar), no blend/gate',
    'theme': ['reversal'],
    'formula_latex': r'-\left(\mathrm{close}_t/\mathrm{close}_{t-20} - 1\right)',
    'columns_required': ['close'],
    'universe': ['crypto'],
    'frequency': ['1h'],
    'decay_horizon': 20,
    'min_warmup_bars': 20,
    'notes': (
        'Sign-flipped custom_crypto_momentum_trend_v2: the symbol-sliced IC check '
        'showed 27/28 symbols with negative IC for raw 20-bar momentum against 5-bar '
        'forward returns (majors worst: BTC -0.090). This alpha tests the reversal '
        'hypothesis directly -- raw 20-bar return, sign-flipped, ranked with no wrapper, '
        'gate, or blend, so the gauntlet result is attributable to the hypothesis change '
        'alone, not to any new parameter.'
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Negative 20-bar return -- past losers rank highest."""
    close = panel['close']
    return -(close.pct_change(20))
