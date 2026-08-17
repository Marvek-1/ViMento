import json
from pathlib import Path

import pandas as pd

from backtest.runner import (
    _coverage_receipt_for_frame,
    _fetch_single_source,
    _market_coverage_ok,
    _stamp_fetch_coverage,
)
from backtest.run_card import write_run_card


def test_coverage_receipt_rejects_truncated_start():
    idx = pd.date_range("2025-11-10", periods=1435, freq="4h")
    df = pd.DataFrame({"close": range(len(idx))}, index=idx)

    receipt = _coverage_receipt_for_frame(
        df,
        requested_start="2023-01-01",
        requested_end="2026-07-07",
        interval="4H",
    )

    assert receipt["coverage_ok"] is False
    assert receipt["coverage_ratio"] < 0.95
    assert "delivered_start" in receipt["window_integrity_error"]


def test_stamp_fetch_coverage_marks_market_not_ok_for_missing_or_truncated_symbol():
    idx = pd.date_range("2025-11-10", periods=1435, freq="4h")
    data_map = {
        "BTC-USDT": pd.DataFrame({"close": range(len(idx))}, index=idx),
    }
    provenance = {
        "BTC-USDT": {
            "requested_source": "auto",
            "attempted_sources": ["okx"],
            "failed_sources": [],
            "successful_source": "okx",
            "bars": 1435,
        },
        "ETH-USDT": {
            "requested_source": "auto",
            "attempted_sources": ["okx"],
            "failed_sources": [],
            "successful_source": "okx",
            "bars": 0,
        },
    }
    config = {
        "source": "auto",
        "start_date": "2023-01-01",
        "end_date": "2026-07-07",
    }

    _stamp_fetch_coverage(provenance, "okx", data_map, ["BTC-USDT", "ETH-USDT"], config, "4H")

    assert provenance["BTC-USDT"]["coverage_ok"] is False
    assert provenance["ETH-USDT"]["coverage_ok"] is False
    assert _market_coverage_ok(provenance, ["BTC-USDT", "ETH-USDT"]) is False


def test_fetch_single_source_rejects_truncated_window(monkeypatch):
    idx = pd.date_range("2025-11-10", periods=1435, freq="4h")
    data_map = {
        "BTC-USDT": pd.DataFrame({"close": range(len(idx))}, index=idx),
    }

    class _Loader:
        name = "okx"

    monkeypatch.setattr("backtest.runner._get_loader", lambda source: _Loader)
    monkeypatch.setattr("backtest.runner._fallback_loader_names_for_codes", lambda codes: [])
    monkeypatch.setattr(
        "backtest.runner._fetch_with_loader",
        lambda loader, codes, config, interval: (data_map, codes),
    )

    config = {
        "source": "okx",
        "start_date": "2023-01-01",
        "end_date": "2026-07-07",
    }

    result, effective_source, _loader, normalized_codes = _fetch_single_source(
        ["BTC-USDT"],
        config,
        "okx",
        "4H",
    )

    provenance = config["_data_source_provenance"]["BTC-USDT"]
    assert result == {}
    assert effective_source == "okx"
    assert normalized_codes == ["BTC-USDT"]
    assert provenance["coverage_ok"] is False
    assert provenance["successful_source"] is None
    assert provenance["failed_sources"][-1]["kind"] == "truncated"


def _write_minimal_artifacts(run_dir: Path) -> Path:
    (run_dir / "artifacts").mkdir(parents=True)
    (run_dir / "artifacts" / "metrics.csv").write_text("metric,value\ntrade_count,250\n")
    (run_dir / "artifacts" / "equity.csv").write_text("timestamp,equity\n2024-01-01,1000\n")
    strategy = run_dir / "code" / "signal_engine.py"
    strategy.parent.mkdir(parents=True)
    strategy.write_text("class SignalEngine:\n    pass\n")
    (run_dir / "config.json").write_text("{}\n")
    return strategy


def test_run_card_requires_window_integrity_for_statistical_evaluability(tmp_path):
    strategy = _write_minimal_artifacts(tmp_path)
    config = {
        "codes": ["BTC-USDT"],
        "source": "auto",
        "start_date": "2023-01-01",
        "end_date": "2026-07-07",
        "_data_source_provenance": {
            "BTC-USDT": {
                "requested_source": "auto",
                "attempted_sources": ["okx"],
                "failed_sources": [],
                "successful_source": None,
                "coverage_ok": False,
                "coverage_ratio": 0.186,
            }
        },
    }

    card = write_run_card(
        tmp_path,
        config,
        {"trade_count": 250, "total_return": 0.1},
        data_sources=["okx"],
        strategy_path=strategy,
    )

    assert card["provenance_valid"] is True
    assert card["window_integrity"] is False
    assert card["statistically_evaluable"] is False
    assert card["hypothesis_supported"] is None


def test_run_card_allows_evaluability_when_window_integrity_and_trade_count_pass(tmp_path):
    strategy = _write_minimal_artifacts(tmp_path)
    config = {
        "codes": ["BTC-USDT"],
        "source": "auto",
        "start_date": "2023-01-01",
        "end_date": "2026-07-07",
        "_data_source_provenance": {
            "BTC-USDT": {
                "requested_source": "auto",
                "attempted_sources": ["binance"],
                "failed_sources": [],
                "successful_source": "binance",
                "coverage_ok": True,
                "coverage_ratio": 0.99,
            }
        },
    }

    card = write_run_card(
        tmp_path,
        config,
        {"trade_count": 250, "total_return": 0.1},
        data_sources=["binance"],
        strategy_path=strategy,
    )

    assert card["window_integrity"] is True
    assert card["statistically_evaluable"] is True
    assert card["hypothesis_supported"] is None


def test_run_card_blocks_evaluability_when_window_integrity_unknown(tmp_path):
    strategy = _write_minimal_artifacts(tmp_path)
    config = {
        "codes": ["BTC-USDT"],
        "source": "auto",
        "start_date": "2023-01-01",
        "end_date": "2026-07-07",
    }

    card = write_run_card(
        tmp_path,
        config,
        {"trade_count": 250, "total_return": 0.1},
        data_sources=["okx"],
        strategy_path=strategy,
    )

    assert card["provenance_valid"] is True
    assert card["window_integrity"] is None
    assert card["statistically_evaluable"] is False
    assert card["hypothesis_supported"] is None


def test_run_card_blocks_evaluability_for_truncated_window_even_with_many_trades(tmp_path):
    strategy = _write_minimal_artifacts(tmp_path)
    config = {
        "codes": ["BTC-USDT"],
        "source": "auto",
        "start_date": "2023-01-01",
        "end_date": "2026-07-07",
        "_data_source_provenance": {
            "BTC-USDT": {
                "requested_source": "auto",
                "attempted_sources": ["okx"],
                "failed_sources": [
                    {"source": "okx", "kind": "truncated", "error": "coverage_ratio below floor"}
                ],
                "successful_source": None,
                "coverage_ok": False,
                "coverage_ratio": 0.186,
            }
        },
    }

    card = write_run_card(
        tmp_path,
        config,
        {"trade_count": 364, "total_return": -0.499},
        data_sources=["okx"],
        strategy_path=strategy,
    )

    assert card["provenance_valid"] is True
    assert card["window_integrity"] is False
    assert card["statistically_evaluable"] is False
    assert card["hypothesis_supported"] is None
