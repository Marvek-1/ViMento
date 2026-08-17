"""Shared requested-window coverage receipts.

A fetch that succeeds on the wrong window is a failure wearing a receipt.
These helpers are shared by strategy data loading and benchmark loading.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd


COVERAGE_FLOOR = 0.95


def interval_to_timedelta(interval: str) -> pd.Timedelta:
    """Convert project interval strings to approximate bar duration."""
    mapping = {
        "1m": pd.Timedelta(minutes=1),
        "5m": pd.Timedelta(minutes=5),
        "15m": pd.Timedelta(minutes=15),
        "30m": pd.Timedelta(minutes=30),
        "1H": pd.Timedelta(hours=1),
        "1h": pd.Timedelta(hours=1),
        "4H": pd.Timedelta(hours=4),
        "4h": pd.Timedelta(hours=4),
        "1D": pd.Timedelta(days=1),
        "1d": pd.Timedelta(days=1),
    }
    return mapping.get(str(interval), pd.Timedelta(days=1))


def expected_bar_count(start_date: str, end_date: str, interval: str) -> int:
    """Expected bars for [start_date, end_date + 1 day) at interval resolution.

    If timestamp math fails, return 0 and let coverage_ok become False.
    """
    try:
        start = pd.Timestamp(str(start_date)).tz_localize(None)
        end_exclusive = (pd.Timestamp(str(end_date)) + pd.Timedelta(days=1)).tz_localize(None)
        step = interval_to_timedelta(str(interval))
        if pd.isna(start) or pd.isna(end_exclusive) or step <= pd.Timedelta(0):
            return 0
        seconds = (end_exclusive - start).total_seconds()
        if seconds <= 0:
            return 0
        return max(1, int(math.ceil(seconds / step.total_seconds())))
    except Exception:  # noqa: BLE001 - coverage metadata must not crash the caller
        return 0


def coverage_receipt_for_frame(
    df: Any,
    *,
    requested_start: str,
    requested_end: str,
    interval: str,
    floor: float = COVERAGE_FLOOR,
) -> dict[str, Any]:
    """Build a coverage receipt for one dataframe.

    True coverage requires:
    - enough bars for the requested window
    - delivered start close to requested start
    - delivered end close to requested end
    """
    expected_bars = expected_bar_count(requested_start, requested_end, interval)
    requested_start_ts = pd.Timestamp(requested_start).tz_localize(None)
    requested_end_exclusive = (pd.Timestamp(requested_end) + pd.Timedelta(days=1)).tz_localize(None)
    step = interval_to_timedelta(interval)

    base = {
        "requested_window": {"start": requested_start, "end": requested_end},
        "expected_bars": expected_bars,
        "coverage_floor": floor,
        "pagination_pages": None,
        "pagination_exhausted": None,
    }

    if df is None or getattr(df, "empty", True):
        return {
            **base,
            "delivered_window": {"start": None, "end": None},
            "delivered_bars": 0,
            "coverage_ratio": 0.0,
            "coverage_ok": False,
            "window_integrity_error": "no_data",
        }

    try:
        idx = pd.DatetimeIndex(df.index).tz_localize(None).sort_values()
        delivered_start = idx.min()
        delivered_end = idx.max()
        delivered_bars = int(len(idx))
    except Exception as exc:  # noqa: BLE001
        return {
            **base,
            "delivered_window": {"start": None, "end": None},
            "delivered_bars": 0,
            "coverage_ratio": 0.0,
            "coverage_ok": False,
            "window_integrity_error": f"bad_index: {type(exc).__name__}: {exc}",
        }

    ratio = float(delivered_bars / expected_bars) if expected_bars else 0.0
    start_ok = delivered_start <= requested_start_ts + (step * 2)
    end_ok = delivered_end >= requested_end_exclusive - (step * 2)
    ratio_ok = ratio >= floor
    coverage_ok = bool(start_ok and end_ok and ratio_ok)

    error_parts: list[str] = []
    if not start_ok:
        error_parts.append(f"delivered_start {delivered_start} after requested_start {requested_start_ts}")
    if not end_ok:
        error_parts.append(f"delivered_end {delivered_end} before requested_end {requested_end_exclusive}")
    if not ratio_ok:
        error_parts.append(f"coverage_ratio {ratio:.3f} below floor {floor:.3f}")

    return {
        **base,
        "delivered_window": {
            "start": delivered_start.isoformat(),
            "end": delivered_end.isoformat(),
        },
        "delivered_bars": delivered_bars,
        "coverage_ratio": ratio,
        "coverage_ok": coverage_ok,
        "window_integrity_error": "; ".join(error_parts) if error_parts else None,
    }


# Backward-compatible aliases for older tests/imports.
_interval_to_timedelta = interval_to_timedelta
_expected_bar_count = expected_bar_count
_coverage_receipt_for_frame = coverage_receipt_for_frame
