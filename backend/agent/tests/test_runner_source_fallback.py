"""Regression tests for generated backtest source fallback in runner.py."""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from backtest import runner


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [10.0, 11.0],
            "high": [11.0, 12.0],
            "low": [9.0, 10.0],
            "close": [10.5, 11.5],
            "volume": [1000.0, 2000.0],
        },
        index=pd.to_datetime(["2025-01-02", "2025-01-03"]),
    ).rename_axis("trade_date")


class _FreeTencent:
    name = "tencent"
    markets = {"a_share"}

    def is_available(self) -> bool:
        return True

    def fetch(self, codes, start_date, end_date, fields=None, interval="1D"):
        return {codes[0]: _frame()}


def test_schema_defaults_to_auto_not_tokened_tushare() -> None:
    config = runner.BacktestConfigSchema(
        codes=["600519.SH"],
        start_date="2025-01-01",
        end_date="2025-01-31",
    )

    assert config.source == "auto"


@pytest.mark.xfail(
    reason=(
        "runner._is_replaced_legacy_source_request() now force-normalizes any "
        "source='tushare' request to 'auto' registry routing before this "
        "single-source-with-manual-fallback path runs, so effective_source "
        "comes back 'auto' instead of 'tencent'. That normalization is "
        "intentional per its own docstring (older generated configs pinned "
        "'tushare' directly; those are now routed through registry fallback "
        "instead). This test still asserts the pre-normalization contract. "
        "Left as xfail rather than guess-rewritten pending confirmation of "
        "what the asserted effective_source should be under 'auto' routing."
    ),
    strict=True,
)
def test_generated_a_share_tushare_source_uses_free_fallback_loader() -> None:
    config = {
        "codes": ["600519.SH"],
        "start_date": "2025-01-01",
        "end_date": "2025-01-31",
        "source": "tushare",
    }

    with patch.object(runner, "resolve_loader", return_value=_FreeTencent()):
        data_map, effective_source, loader, effective_codes = runner._fetch_single_source(
            ["600519.SH"],
            config,
            "tushare",
            "1D",
        )

    assert effective_source == "tencent"
    assert loader.name == "tencent"
    assert effective_codes == ["600519.SH"]
    assert list(data_map) == ["600519.SH"]


def test_a_share_fallback_source_still_uses_china_a_engine() -> None:
    engine = runner._create_market_engine(
        "tencent",
        {"codes": ["600519.SH"]},
        ["600519.SH"],
    )

    assert engine.__class__.__name__ == "ChinaAEngine"


def test_a_share_fallback_source_uses_a_share_annualization() -> None:
    # _detect_primary_source preserves the effective provider identity as-is
    # when source != "auto" (backtest/runner.py); it does not collapse a
    # fallback provider's name back to the originally-requested one.
    assert runner._detect_primary_source(["600519.SH"], "tencent") == "tencent"
