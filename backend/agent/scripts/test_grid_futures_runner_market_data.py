"""Proves grid_futures_runner threads the real price-fetch source into
sync_tick's market_data_source instead of the previous hardcoded
"gate_fallback" label -- see paper_session.fetch_last_prices_with_source.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest

import grid_futures_runner
from paper_session import PriceFetchResult
from paper_postgres import WorkerIdentity


class _FakePostgres:
    """Records sync_tick calls without touching a real database."""

    instances: list["_FakePostgres"] = []

    def __init__(self, identity: WorkerIdentity) -> None:
        self.identity = identity
        self.sync_tick_calls: list[dict] = []
        _FakePostgres.instances.append(self)

    def sync_tick(self, *args, **kwargs) -> None:
        self.sync_tick_calls.append(kwargs)

    def heartbeat(self, _pid: int) -> None:
        pass

    def close(self) -> None:
        pass


def _write_universe(path: Path, symbols: list[str]) -> None:
    payload_hash = hashlib.sha256(
        json.dumps(symbols, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    path.write_text(json.dumps({"symbols": symbols, "symbols_sha256": payload_hash}), encoding="utf-8")


def _make_session_dir(tmp_path: Path) -> Path:
    session_dir = tmp_path / "candidate_5m_futures"
    session_dir.mkdir()
    _write_universe(session_dir / "universe.json", ["BTC-USDT"])
    (session_dir / "session_config.json").write_text(
        json.dumps({
            "initial_balance": 10000,
            "universe_path": "universe.json",
            "leverage": 10,
            "margin_per_trade": 20,
        }),
        encoding="utf-8",
    )
    return session_dir


@pytest.fixture(autouse=True)
def _reset_fake_postgres_registry():
    _FakePostgres.instances.clear()
    yield
    _FakePostgres.instances.clear()


def test_run_passes_fetched_source_into_sync_tick(tmp_path, monkeypatch):
    session_dir = _make_session_dir(tmp_path)
    monkeypatch.setenv("PAPER_CANDIDATE_5M_CAPITAL", "10000")
    monkeypatch.setattr(grid_futures_runner, "PaperPostgres", _FakePostgres)
    monkeypatch.setattr(
        grid_futures_runner,
        "fetch_last_prices_with_source",
        lambda symbols: PriceFetchResult(prices={s: 100.0 for s in symbols}, source="okx"),
    )

    def _stop_after_first_tick(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(grid_futures_runner.time, "sleep", _stop_after_first_tick)

    identity = WorkerIdentity(
        account_id=uuid4(), strategy_id="candidate", worker_id="candidate_5m",
        timeframe="5m", mode="paper", leverage=10,
    )
    # PaperPostgres._verify_account() would normally cross-check the DB; the
    # fake postgres above bypasses it entirely, so any syntactically valid
    # account_id/leverage combination is fine here -- this test only
    # exercises the price-source plumbing in run().
    # policy_for("5m").decision_interval_seconds == 300 -- run() now refuses
    # to start unless poll_seconds matches the timeframe's own cadence.
    with pytest.raises(KeyboardInterrupt):
        grid_futures_runner.run(session_dir, poll_seconds=300, identity=identity)

    [fake_postgres] = _FakePostgres.instances
    assert len(fake_postgres.sync_tick_calls) == 1
    assert fake_postgres.sync_tick_calls[0]["market_data_source"] == "okx"
    assert fake_postgres.sync_tick_calls[0]["market_data_source"] != "gate_fallback"
    assert fake_postgres.sync_tick_calls[0]["market_data_fresh"] is True


def test_run_does_not_hardcode_gate_fallback(tmp_path, monkeypatch):
    session_dir = _make_session_dir(tmp_path)
    monkeypatch.setenv("PAPER_CANDIDATE_5M_CAPITAL", "10000")
    monkeypatch.setattr(grid_futures_runner, "PaperPostgres", _FakePostgres)
    monkeypatch.setattr(
        grid_futures_runner,
        "fetch_last_prices_with_source",
        lambda symbols: PriceFetchResult(prices={s: 100.0 for s in symbols}, source="binance"),
    )

    def _stop_after_first_tick(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(grid_futures_runner.time, "sleep", _stop_after_first_tick)

    identity = WorkerIdentity(
        account_id=uuid4(), strategy_id="candidate", worker_id="candidate_5m",
        timeframe="5m", mode="paper", leverage=10,
    )

    # policy_for("5m").decision_interval_seconds == 300 -- run() now refuses
    # to start unless poll_seconds matches the timeframe's own cadence.
    with pytest.raises(KeyboardInterrupt):
        grid_futures_runner.run(session_dir, poll_seconds=300, identity=identity)

    [fake_postgres] = _FakePostgres.instances
    assert fake_postgres.sync_tick_calls[0]["market_data_source"] == "binance"
