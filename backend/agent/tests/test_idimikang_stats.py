"""Tests for IdimIkang signal statistics computation."""

import math
from typing import Any

import pytest

from src.idimikang.stats import compute_signal_stats


def _sig(outcome: str, r: float) -> dict[str, Any]:
    return {"outcome": outcome, "r_multiple": r}


def test_profit_factor_and_count_ratio() -> None:
    signals = [
        _sig("WIN", 0.6),
        _sig("WIN", 0.6),
        _sig("LOSS", -1.0),
        _sig("PENDING", 0.0),  # unresolved, ignored for PF and resolved count
    ]
    stats = compute_signal_stats(signals)
    assert math.isclose(stats["profit_factor"], 1.2)
    assert stats["win_loss_count_ratio"] == 2.0
    assert stats["wins"] == 2
    assert stats["losses"] == 1
    assert stats["resolved"] == 3
    assert stats["abstained"] == 1
    assert stats["coverage"] == 0.75
    assert math.isclose(stats["gross_positive_r"], 1.2)
    assert math.isclose(stats["gross_negative_r"], 1.0)
    assert math.isclose(stats["expectancy"], (1.2 - 1.0) / 3)


def test_no_losses_profit_factor_is_none() -> None:
    signals = [_sig("WIN", 0.5), _sig("PENDING", 0.0)]
    stats = compute_signal_stats(signals)
    assert stats["profit_factor"] is None
    assert stats["win_loss_count_ratio"] == math.inf
    assert stats["coverage"] == 0.5


def test_no_resolved_signals() -> None:
    signals = [_sig("PENDING", 0.0), _sig("ABSTAINED", 0.0)]
    stats = compute_signal_stats(signals)
    assert stats["profit_factor"] is None
    assert stats["win_loss_count_ratio"] is None
    assert stats["wins"] == 0
    assert stats["losses"] == 0
    assert stats["resolved"] == 0
    assert stats["abstained"] == 2
    assert stats["coverage"] == 0.0
    assert stats["expectancy"] is None


def test_empty_signals() -> None:
    stats = compute_signal_stats([])
    assert stats["profit_factor"] is None
    assert stats["win_loss_count_ratio"] is None
    assert stats["coverage"] == 0.0


def test_rejects_sign_mismatch() -> None:
    signals = [
        _sig("WIN", -1.0),
        _sig("LOSS", 0.6),
    ]
    with pytest.raises(ValueError, match="outcome/r_multiple sign mismatch"):
        compute_signal_stats(signals)


def test_rejects_zero_r_for_win() -> None:
    with pytest.raises(ValueError, match="outcome/r_multiple sign mismatch"):
        compute_signal_stats([_sig("WIN", 0.0)])


def test_rejects_zero_r_for_loss() -> None:
    with pytest.raises(ValueError, match="outcome/r_multiple sign mismatch"):
        compute_signal_stats([_sig("LOSS", 0.0)])
