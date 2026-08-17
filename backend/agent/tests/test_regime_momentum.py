"""Unit tests for the regime_momentum strategy."""

import numpy as np
import pandas as pd

from research import strategies


def _prices(rows: list[list[float]], symbols=None, index_start: int = 0) -> pd.DataFrame:
    symbols = symbols or ["A", "B", "C"]
    return pd.DataFrame(rows, columns=symbols, index=range(index_start, index_start + len(rows)))


def test_insufficient_history_falls_back_to_equal_weight():
    prices = _prices([[1.0, 1.0, 1.0], [1.1, 0.9, 1.0]])
    weights = strategies.regime_momentum(prices, lookback=24, sma_period=50, top_n=3)
    assert weights == {"A": 1.0 / 3, "B": 1.0 / 3, "C": 1.0 / 3}


def test_only_eligible_above_sma_are_selected():
    # A and B trend up; C is flat and ends exactly at its SMA (not above).
    a = np.linspace(100, 110, 50)
    b = np.linspace(100, 120, 50)
    c = np.linspace(100, 100, 50)

    prices = pd.DataFrame({"A": a, "B": b, "C": c}, index=range(50))
    weights = strategies.regime_momentum(prices, lookback=24, sma_period=50, top_n=2)

    # A and B are above their SMAs; C is not.
    assert "A" in weights
    assert "B" in weights
    assert "C" not in weights
    assert len(weights) == 2
    assert sum(weights.values()) == 1.0


def test_returns_empty_when_nothing_above_sma():
    prices = _prices([[float(i) for _ in range(3)] for i in range(50, 0, -1)])
    weights = strategies.regime_momentum(prices, lookback=24, sma_period=50, top_n=3)
    assert weights == {}


def test_top_n_limits_selection():
    # 50 bars: A flat, B strong up, C moderate up.
    a = np.linspace(100, 100, 50)
    b = np.linspace(100, 120, 50)
    c = np.linspace(100, 110, 50)
    prices = pd.DataFrame({"A": a, "B": b, "C": c}, index=range(50))

    weights = strategies.regime_momentum(prices, lookback=24, sma_period=50, top_n=2)
    # All above SMA; top 2 by recent 24-bar return should be B and C.
    assert set(weights.keys()) == {"B", "C"}
    assert weights["B"] == weights["C"] == 0.5
