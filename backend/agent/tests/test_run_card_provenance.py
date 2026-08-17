import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import pandas as pd
import pytest

from backtest.runner import main
from backtest.run_card import write_run_card

def create_mock_loader(name, fetch_result=None, exception=None):
    class MockLoader:
        def __init__(self, *args, **kwargs):
            self.name = name
        def is_available(self):
            return True
        def fetch(self, codes, *args, **kwargs):
            if exception:
                raise exception
            if fetch_result is not None:
                return fetch_result
            return {}
    return MockLoader

def test_single_successful_source_recorded(tmp_path: Path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "config.json").write_text(json.dumps({
        "source": "binance",
        "codes": ["BTC-USDT"],
        "start_date": "2024-01-01",
        "end_date": "2024-03-31"
    }))
    (run_dir / "code").mkdir()
    (run_dir / "code" / "signal_engine.py").write_text("""
class SignalEngine:
    def generate(self, data_map):
        import pandas as pd
        return {code: pd.Series(1, index=frame.index) for code, frame in data_map.items()}
""")

    # Coverage gate requires delivered bars to cover the requested window
    # (2024-01-01..2024-03-31, 91 daily bars at 1D) at >=95% ratio -- a
    # 2-row fixture was correctly rejected by that gate, not a bug in it.
    dates = pd.date_range("2024-01-01", "2024-03-31", freq="D")
    df = pd.DataFrame({"close": range(len(dates))}, index=dates)
    loader_cls = create_mock_loader("binance", {"BTC-USDT": df})

    with patch("src.tools.path_utils.safe_run_dir", return_value=run_dir), \
         patch("write_receipt.assert_not_scaffold", return_value="hash123"), \
         patch("backtest.runner._get_loader", return_value=loader_cls), \
         patch("backtest.runner._fallback_loader_names_for_codes", return_value=[]), \
         patch("backtest.run_card.write_run_card") as mock_write:
        main(run_dir)
        
        config = mock_write.call_args[0][1]
        prov = config["_data_source_provenance"]["BTC-USDT"]
        assert prov["requested_source"] == "binance"
        assert prov["attempted_sources"] == ["binance"]
        assert prov["failed_sources"] == []
        assert prov["successful_source"] == "binance"
        assert prov["bars"] == len(dates)

def test_fallback_failures_recorded_before_success(tmp_path: Path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "config.json").write_text(json.dumps({
        "source": "auto",
        "codes": ["BTC-USDT"],
        "start_date": "2024-01-01",
        "end_date": "2024-03-31"
    }))
    (run_dir / "code").mkdir()
    (run_dir / "code" / "signal_engine.py").write_text("""
class SignalEngine:
    def generate(self, data_map):
        import pandas as pd
        return {code: pd.Series(1, index=frame.index) for code, frame in data_map.items()}
""")

    # Same full-window fixture requirement as test_single_successful_source_recorded.
    dates = pd.date_range("2024-01-01", "2024-03-31", freq="D")
    df = pd.DataFrame({"close": range(len(dates))}, index=dates)

    loader_fail = create_mock_loader("binance", exception=ValueError("API Down"))
    loader_ok = create_mock_loader("okx", {"BTC-USDT": df})
    
    def mock_resolve(market):
        return loader_fail()
        
    def mock_instantiate(name):
        # _fetch_auto builds its candidate list via _instantiate_if_available
        # per FALLBACK_CHAINS entry, not via resolve_loader -- that path is
        # only a last-resort fallback when the chain yields zero candidates.
        # binance must resolve to an instantiated (failing) loader here, not
        # None, or its failure never reaches _record_fetch_error with the
        # "API Down" exception -- it would show up as "Loader unavailable"
        # instead, from the chain-building loop, not the fetch-attempt loop.
        if name == "binance":
            return loader_fail()
        if name == "okx":
            return loader_ok()
        return None

    with patch("src.tools.path_utils.safe_run_dir", return_value=run_dir), \
         patch("write_receipt.assert_not_scaffold", return_value="hash123"), \
         patch("backtest.runner.resolve_loader", side_effect=mock_resolve), \
         patch("backtest.runner.FALLBACK_CHAINS", {"crypto": ["binance", "okx"]}), \
         patch("backtest.runner._instantiate_if_available", side_effect=mock_instantiate), \
         patch("backtest.run_card.write_run_card") as mock_write:
        main(run_dir)

        config = mock_write.call_args[0][1]
        prov = config["_data_source_provenance"]["BTC-USDT"]
        assert prov["requested_source"] == "auto"
        assert prov["attempted_sources"] == ["binance", "okx"]
        assert len(prov["failed_sources"]) == 1
        assert prov["failed_sources"][0]["source"] == "binance"
        assert "API Down" in prov["failed_sources"][0]["error"]
        assert prov["successful_source"] == "okx"

def test_total_failure_records_attempted_and_no_data(tmp_path: Path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "config.json").write_text(json.dumps({
        "source": "auto",
        "codes": ["BTC-USDT"],
        "start_date": "2024-01-01",
        "end_date": "2024-03-31"
    }))
    (run_dir / "code").mkdir()
    (run_dir / "code" / "signal_engine.py").write_text("""
class SignalEngine:
    def generate(self, data_map):
        import pandas as pd
        return {"BTC-USDT": pd.Series([1, 1], index=pd.date_range("2024-01-01", periods=2))}
""")

    loader_fail = create_mock_loader("binance", exception=ValueError("API Down"))
    loader_fail2 = create_mock_loader("okx", exception=ValueError("Timeout"))
    
    def mock_resolve(market):
        return loader_fail()
        
    def mock_instantiate(name):
        if name == "okx":
            return loader_fail2()
        return None

    with patch("src.tools.path_utils.safe_run_dir", return_value=run_dir), \
         patch("write_receipt.assert_not_scaffold", return_value="hash123"), \
         patch("backtest.runner.resolve_loader", side_effect=mock_resolve), \
         patch("backtest.runner.FALLBACK_CHAINS", {"crypto": ["binance", "okx"]}), \
         patch("backtest.runner._instantiate_if_available", side_effect=mock_instantiate), \
         patch("backtest.run_card.write_run_card") as mock_write, \
         pytest.raises(SystemExit):
        main(run_dir)
        
        config = mock_write.call_args[0][1]
        metrics = mock_write.call_args[0][2]
        assert metrics["status"] == "error"
        
        prov = config["_data_source_provenance"]["BTC-USDT"]
        assert prov["requested_source"] == "auto"
        assert prov["attempted_sources"] == ["binance", "okx"]
        assert len(prov["failed_sources"]) == 2
        assert prov["failed_sources"][0]["source"] == "binance"
        assert prov["failed_sources"][1]["source"] == "okx"
        assert prov["successful_source"] is None

def test_run_card_strict_json_passes(tmp_path: Path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    config = {
        "_data_source_provenance": {
            "BTC-USDT": {
                "requested_source": "auto",
                "attempted_sources": ["binance", "bybit"],
                "failed_sources": [
                    {"source": "binance", "error": "API Error"}
                ],
                "successful_source": "bybit",
                "bars": 100,
                "start": "2024-01-01",
                "end": "2024-04-10"
            }
        },
        "codes": ["BTC-USDT"],
        "interval": "1D",
        "start_date": "2024-01-01",
        "end_date": "2024-04-10",
        "engine": "daily",
        "initial_cash": 100000,
        "source": "auto"
    }
    
    write_run_card(run_dir, config, {"sharpe": 1.5})
    
    card = json.loads((run_dir / "run_card.json").read_text())
    assert "data_source_provenance" in card
    assert card["data_source_provenance"]["BTC-USDT"]["successful_source"] == "bybit"
