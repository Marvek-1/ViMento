from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import api_server
import paper_session
import src.api.paper_session_routes as paper_routes


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _write_minimal_session(session_dir, *, mark_timestamp: str | None) -> None:
    """A bare session directory: just enough for _summarize() to load it."""
    session_dir.mkdir(parents=True)
    session = {
        "strategy_type": paper_session.STRATEGY_TYPE,
        "symbols": ["AAA-USDT"],
        "initial_cash": 100.0,
        "entry_time": "2026-07-01T00:00:00+00:00",
        "rebalance_interval_hours": 1.0,
        "fee_rate": 0.0,
    }
    (session_dir / "session.json").write_text(json.dumps(session), encoding="utf-8")
    (session_dir / "book.json").write_text(
        json.dumps({"positions": {"AAA-USDT": 0.0}, "cash_remaining": 100.0, "last_rebalance_time": None}),
        encoding="utf-8",
    )
    (session_dir / "trades.jsonl").write_text("", encoding="utf-8")
    if mark_timestamp is None:
        (session_dir / "marks.jsonl").write_text("", encoding="utf-8")
    else:
        mark = {"timestamp": mark_timestamp, "prices": {"AAA-USDT": 1.0}, "equity": 100.0, "cash_remaining": 100.0}
        (session_dir / "marks.jsonl").write_text(json.dumps(mark) + "\n", encoding="utf-8")


def _write_futures_session(
    session_dir,
    *,
    leverage: int = 5,
    launched: bool = False,
    mark_timestamp: str | None = None,
) -> None:
    """A bare FuturesPaperEngine-schema session: session_config.json plus,
    only if ``launched``, the runtime-state files the engine itself writes
    (account.json/trades.jsonl/marks.jsonl). Mirrors grid_futures_10x_v2's
    real on-disk shape when it was created but never started.
    """
    session_dir.mkdir(parents=True)
    config = {
        "account_id": session_dir.name,
        "engine": "futures_paper_engine.FuturesPaperEngine",
        "adapter": "many_bots_futures_adapter.ManyBotsFuturesAdapter",
        "initial_balance": 25000.0,
        "margin_mode": "isolated",
        "leverage": leverage,
        "margin_per_trade": 20.0,
        "expected_notional_per_trade": 20.0 * leverage,
        "universe_path": "../universe_frozen_canary8.json",
        "status": "INITIALIZED_NOT_LAUNCHED",
    }
    (session_dir / "session_config.json").write_text(json.dumps(config), encoding="utf-8")
    if launched:
        state = {
            "schema_version": 1,
            "initial_balance": 25000.0,
            "wallet_balance": 25000.0,
            "reserved_margin": 0.0,
            "opened_trades": 1,
            "closed_trades": 0,
            "positions": {},
        }
        (session_dir / "account.json").write_text(json.dumps(state), encoding="utf-8")
        (session_dir / "trades.jsonl").write_text("", encoding="utf-8")
        if mark_timestamp is None:
            (session_dir / "marks.jsonl").write_text("", encoding="utf-8")
        else:
            mark = {"timestamp": mark_timestamp, "current_equity": 25000.0}
            (session_dir / "marks.jsonl").write_text(json.dumps(mark) + "\n", encoding="utf-8")


def _write_registry(path, *, active: list[str], archived: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": 1, "active_sessions": active, "archived_sessions": archived}),
        encoding="utf-8",
    )


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(paper_routes, "PAPER_SESSIONS_DIR", tmp_path / "paper_sessions")
    monkeypatch.setattr(paper_routes, "REGISTRY_PATH", tmp_path / "config" / "paper_sessions_registry.json")
    (tmp_path / "paper_sessions").mkdir()
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def _six(prefix: str) -> list[str]:
    return [f"{prefix}_{i}" for i in range(6)]


def _seed_six_active_six_archived(tmp_path, *, fresh: bool) -> None:
    sessions_dir = tmp_path / "paper_sessions"
    active_ts = _iso(datetime.now(timezone.utc) - (timedelta(minutes=1) if fresh else timedelta(minutes=30)))
    for sid in _six("active"):
        _write_minimal_session(sessions_dir / sid, mark_timestamp=active_ts)
    for sid in _six("archived"):
        _write_minimal_session(sessions_dir / sid, mark_timestamp="2026-07-01T00:00:00+00:00")
    _write_registry(
        tmp_path / "config" / "paper_sessions_registry.json",
        active=_six("active"),
        archived=_six("archived"),
    )


def test_registry_loads_successfully(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(paper_routes, "REGISTRY_PATH", tmp_path / "config" / "paper_sessions_registry.json")
    _write_registry(tmp_path / "config" / "paper_sessions_registry.json", active=["a"], archived=["b"])

    active_ids, archived_ids, error = paper_routes._load_registry()

    assert error is None
    assert active_ids == frozenset({"a"})
    assert archived_ids == frozenset({"b"})


def test_default_endpoint_returns_exactly_six_active_sessions(tmp_path, client) -> None:
    _seed_six_active_six_archived(tmp_path, fresh=True)

    response = client.get("/paper-sessions")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 6
    assert {s["session_id"] for s in body} == set(_six("active"))
    assert all(s["classification"] == "active" for s in body)


def test_scope_archived_returns_the_six_frozen_sessions(tmp_path, client) -> None:
    _seed_six_active_six_archived(tmp_path, fresh=True)

    response = client.get("/paper-sessions", params={"scope": "archived"})

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 6
    assert {s["session_id"] for s in body} == set(_six("archived"))
    assert all(s["classification"] == "archived" for s in body)


def test_scope_all_returns_both_groups(tmp_path, client) -> None:
    _seed_six_active_six_archived(tmp_path, fresh=True)

    response = client.get("/paper-sessions", params={"scope": "all"})

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 12
    assert {s["session_id"] for s in body} == set(_six("active")) | set(_six("archived"))


def test_unknown_directory_is_not_treated_as_active(tmp_path, client) -> None:
    sessions_dir = tmp_path / "paper_sessions"
    _write_minimal_session(sessions_dir / "funding_live", mark_timestamp=_iso(datetime.now(timezone.utc)))
    _write_registry(tmp_path / "config" / "paper_sessions_registry.json", active=[], archived=[])

    response_active = client.get("/paper-sessions")
    response_all = client.get("/paper-sessions", params={"scope": "all"})

    # Not registry-covered -> never excluded by scope, but never labeled active either.
    assert response_active.status_code == 200
    assert [s["classification"] for s in response_active.json()] == ["unknown"]
    assert response_all.status_code == 200
    assert [s["classification"] for s in response_all.json()] == ["unknown"]


def test_archived_session_cannot_report_running(tmp_path, client) -> None:
    sessions_dir = tmp_path / "paper_sessions"
    # Fresh mark + fresh heartbeat, but the registry says archived -- must still not be "running".
    _write_minimal_session(sessions_dir / "old_but_archived", mark_timestamp=_iso(datetime.now(timezone.utc)))
    (sessions_dir / "old_but_archived" / ".heartbeat").write_text(_iso(datetime.now(timezone.utc)), encoding="utf-8")
    _write_registry(
        tmp_path / "config" / "paper_sessions_registry.json",
        active=[],
        archived=["old_but_archived"],
    )

    response = client.get("/paper-sessions", params={"scope": "archived"})

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["classification"] == "archived"
    assert body[0]["status"] == "archived"
    assert body[0]["status"] != "running"


def test_fresh_active_mark_reports_running(tmp_path, client) -> None:
    _seed_six_active_six_archived(tmp_path, fresh=True)

    response = client.get("/paper-sessions")

    assert all(s["status"] == "running" for s in response.json())


def test_stale_active_mark_reports_stale(tmp_path, client) -> None:
    _seed_six_active_six_archived(tmp_path, fresh=False)

    response = client.get("/paper-sessions")

    assert all(s["status"] == "stale" for s in response.json())


def test_missing_registry_fails_closed(tmp_path, client) -> None:
    sessions_dir = tmp_path / "paper_sessions"
    _write_minimal_session(sessions_dir / "some_session", mark_timestamp=_iso(datetime.now(timezone.utc)))
    # No registry file written at all.

    response = client.get("/paper-sessions", params={"scope": "all"})

    assert response.status_code == 200
    assert response.json() == []

    status_response = client.get("/paper-sessions/registry-status")
    assert status_response.json()["registry_status"] == "error"


# ── grid_futures / funding_live discoverability (dashboard compat patch) ──


def test_active_scope_includes_grid_futures() -> None:
    """The real repo registry -- not a tmp_path fixture -- must list both
    grid_futures accounts as active, or the Grid Futures dashboard tab goes
    back to silently empty."""
    active_ids, archived_ids, error = paper_routes._load_registry()

    assert error is None
    assert {
        "grid_futures_10x_v3",
        "grid_futures_5x_v3",
        "morning_glory_futures",
    }.issubset(active_ids)


def test_funding_live_is_quarantined_not_active() -> None:
    """funding_live was moved to archived_sessions after the forensic audit
    found its risk-exit settlement was broken (see
    paper_sessions/_quarantine/funding_live_accounting_invalid_*/
    QUARANTINE_NOTICE.md) -- it must not silently reappear as active until
    a corrected replay supersedes it."""
    active_ids, archived_ids, error = paper_routes._load_registry()

    assert error is None
    assert "funding_live" not in active_ids
    assert "funding_live" in archived_ids


def test_futures_config_session_is_discovered_without_session_json(tmp_path, client) -> None:
    sessions_dir = tmp_path / "paper_sessions"
    _write_futures_session(sessions_dir / "grid_test", leverage=5, launched=False)
    _write_registry(tmp_path / "config" / "paper_sessions_registry.json", active=["grid_test"], archived=[])

    response = client.get("/paper-sessions")

    assert response.status_code == 200
    body = response.json()
    assert [s["session_id"] for s in body] == ["grid_test"]
    assert body[0]["classification"] == "active"


def test_unstarted_futures_session_has_empty_positions(tmp_path, client) -> None:
    sessions_dir = tmp_path / "paper_sessions"
    _write_futures_session(sessions_dir / "grid_test", leverage=5, launched=False)
    _write_registry(tmp_path / "config" / "paper_sessions_registry.json", active=["grid_test"], archived=[])

    response = client.get("/paper-sessions")

    body = response.json()[0]
    assert body["book"] is None
    assert body["trade_count"] == 0
    assert body["mark_count"] == 0
    assert body["status"] == "not_started"
    assert body["active"] is False


def test_launched_futures_session_reports_running_from_fresh_marks(tmp_path, client) -> None:
    sessions_dir = tmp_path / "paper_sessions"
    _write_futures_session(
        sessions_dir / "grid_test",
        leverage=5,
        launched=True,
        mark_timestamp=_iso(datetime.now(timezone.utc)),
    )
    _write_registry(tmp_path / "config" / "paper_sessions_registry.json", active=["grid_test"], archived=[])

    response = client.get("/paper-sessions")

    body = response.json()[0]
    assert body["status"] == "running"
    assert body["active"] is True
    assert body["latest_mark"]["equity"] == 25000.0


def test_futures_leverage_comes_from_session_config(tmp_path, client) -> None:
    sessions_dir = tmp_path / "paper_sessions"
    _write_futures_session(sessions_dir / "grid_test", leverage=5, launched=False)
    _write_registry(tmp_path / "config" / "paper_sessions_registry.json", active=["grid_test"], archived=[])

    response = client.get("/paper-sessions")

    body = response.json()[0]
    assert body["session"]["risk_config"]["leverage"] == 5


def test_existing_funding_positions_keep_open_leverage(tmp_path, client) -> None:
    """A session-level leverage change (e.g. 2x -> 5x) must never rewrite the
    leverage recorded on a position that already opened at the old value --
    that leverage is baked into the position's margin/liquidation math."""
    sessions_dir = tmp_path / "paper_sessions"
    session_dir = sessions_dir / "funding_like"
    session_dir.mkdir(parents=True)
    session = {
        "strategy_type": "funding_rate_zscore",
        "symbols": ["BTC-USDT"],
        "initial_cash": 10000.0,
        "entry_time": "2026-07-23T00:00:00+00:00",
        "risk_config": {"leverage": 5.0, "margin_mode": "isolated"},
    }
    (session_dir / "session.json").write_text(json.dumps(session), encoding="utf-8")
    book = {
        "positions": {"BTC-USDT": -0.001},
        "cash_remaining": 9000.0,
        "position_metadata": {
            "BTC-USDT": {
                "symbol": "BTC-USDT",
                "leverage": 2.0,
                "margin": 0.0,
                "direction": -1,
                "entry_time": "2026-07-23T00:00:00+00:00",
            }
        },
    }
    (session_dir / "book.json").write_text(json.dumps(book), encoding="utf-8")
    (session_dir / "trades.jsonl").write_text("", encoding="utf-8")
    (session_dir / "marks.jsonl").write_text("", encoding="utf-8")
    _write_registry(tmp_path / "config" / "paper_sessions_registry.json", active=["funding_like"], archived=[])

    response = client.get("/paper-sessions")

    body = response.json()[0]
    assert body["session"]["risk_config"]["leverage"] == 5.0
    assert body["book"]["position_metadata"]["BTC-USDT"]["leverage"] == 2.0


def test_scope_all_does_not_duplicate_sessions(tmp_path, client) -> None:
    sessions_dir = tmp_path / "paper_sessions"
    _write_minimal_session(sessions_dir / "legacy_one", mark_timestamp=_iso(datetime.now(timezone.utc)))
    _write_futures_session(sessions_dir / "futures_one", leverage=5, launched=False)
    _write_registry(
        tmp_path / "config" / "paper_sessions_registry.json",
        active=["legacy_one", "futures_one"],
        archived=[],
    )

    response = client.get("/paper-sessions", params={"scope": "all"})

    ids = [s["session_id"] for s in response.json()]
    assert sorted(ids) == ["futures_one", "legacy_one"]
    assert len(ids) == len(set(ids))


def test_malformed_registry_fails_closed(tmp_path, client) -> None:
    sessions_dir = tmp_path / "paper_sessions"
    _write_minimal_session(sessions_dir / "some_session", mark_timestamp=_iso(datetime.now(timezone.utc)))
    registry_path = tmp_path / "config" / "paper_sessions_registry.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text("{not valid json", encoding="utf-8")

    response = client.get("/paper-sessions", params={"scope": "all"})

    assert response.status_code == 200
    assert response.json() == []

    status_response = client.get("/paper-sessions/registry-status")
    assert status_response.json()["registry_status"] == "error"
