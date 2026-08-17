import json

import pytest

from verify_multileg_gate import db_counts_by_symbol, run_gate


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, sql, params=None):
        pass

    def fetchall(self):
        return self.rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConn:
    def __init__(self, rows):
        self.rows = rows

    def cursor(self):
        return FakeCursor(self.rows)


def write_account_json(tmp_path, positions):
    path = tmp_path / "account.json"
    path.write_text(json.dumps({"positions": positions}), encoding="utf-8")
    return path


def test_gate_not_exercised_for_single_leg(tmp_path):
    path = write_account_json(tmp_path, {"leg-1": {"symbol": "BTCUSDT", "trade_id": "leg-1"}})
    result = run_gate(FakeConn([("grid_futures_5x", "BTCUSDT", 1, 1)]), "grid_futures_5x", path)
    assert result["multileg_observed"] is False
    assert result["any_mismatch"] is False


def test_gate_passes_matching_multileg_state(tmp_path):
    positions = {f"leg-{i}": {"symbol": "BTCUSDT", "trade_id": f"leg-{i}"} for i in range(1, 4)}
    path = write_account_json(tmp_path, positions)
    result = run_gate(FakeConn([("grid_futures_5x", "BTCUSDT", 3, 3)]), "grid_futures_5x", path)
    assert result["multileg_observed"] is True
    assert result["any_mismatch"] is False
    assert result["rows"][0]["engine_open_legs"] == result["rows"][0]["db_row_count"] == 3


def test_gate_detects_engine_database_divergence(tmp_path):
    positions = {f"leg-{i}": {"symbol": "BTCUSDT", "trade_id": f"leg-{i}"} for i in range(1, 4)}
    path = write_account_json(tmp_path, positions)
    result = run_gate(FakeConn([("grid_futures_5x", "BTCUSDT", 2, 2)]), "grid_futures_5x", path)
    assert result["any_mismatch"] is True
    assert result["rows"][0]["match"] is False


def test_primary_key_integrity_failure_is_fatal():
    with pytest.raises(RuntimeError, match="PRIMARY KEY INTEGRITY FAILURE"):
        db_counts_by_symbol(FakeConn([("grid_futures_5x", "BTCUSDT", 3, 2)]), "grid_futures_5x")
