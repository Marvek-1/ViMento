"""IdimIkang signal-statistics utilities with honest profit-factor accounting."""

from __future__ import annotations

from math import inf
from typing import Any


def compute_signal_stats(signals: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute profit-factor and win/loss metrics from all emitted signals.

    ``signals`` must contain **all** emitted rows for the measurement window,
    including unresolved states (PENDING, ABSTAINED, SKIPPED). Only rows with
    ``outcome`` in ``(\"WIN\", \"LOSS\")`` are treated as resolved.

    ``profit_factor`` is gross positive R divided by the absolute value of
    gross negative R. ``win_loss_count_ratio`` is the count of wins divided by
    the count of losses. They are intentionally separate metrics.
    """
    emitted = len(signals)

    resolved = [s for s in signals if s.get("outcome") in ("WIN", "LOSS")]
    wins = [s for s in resolved if s["outcome"] == "WIN"]
    losses = [s for s in resolved if s["outcome"] == "LOSS"]

    invalid_sign_rows: list[dict[str, Any]] = []
    positive_r_values: list[float] = []
    negative_r_values: list[float] = []

    for s in wins:
        r = float(s.get("r_multiple", 0.0))
        if r <= 0:
            invalid_sign_rows.append(s)
        else:
            positive_r_values.append(r)

    for s in losses:
        r = float(s.get("r_multiple", 0.0))
        if r >= 0:
            invalid_sign_rows.append(s)
        else:
            negative_r_values.append(r)

    if invalid_sign_rows:
        raise ValueError(
            f"Invalid resolved signal rows: {len(invalid_sign_rows)} "
            "records have outcome/r_multiple sign mismatch"
        )

    gross_positive_r = sum(positive_r_values)
    gross_negative_r = abs(sum(negative_r_values))

    if gross_negative_r > 0:
        profit_factor = gross_positive_r / gross_negative_r
    else:
        profit_factor = None

    win_loss_count_ratio = (
        len(wins) / len(losses)
        if len(losses) > 0
        else (inf if len(wins) > 0 else None)
    )

    resolved_cnt = len(resolved)
    abstained = emitted - resolved_cnt
    coverage = (resolved_cnt / emitted) if emitted else 0.0

    expectancy = (
        sum(float(s.get("r_multiple", 0.0)) for s in resolved) / resolved_cnt
        if resolved_cnt > 0
        else None
    )

    return {
        "profit_factor": profit_factor,
        "win_loss_count_ratio": win_loss_count_ratio,
        "wins": len(wins),
        "losses": len(losses),
        "resolved": resolved_cnt,
        "abstained": abstained,
        "coverage": coverage,
        "gross_positive_r": gross_positive_r,
        "gross_negative_r": gross_negative_r,
        "expectancy": expectancy,
    }
