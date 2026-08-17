from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import api_server
from src.idimikang.store import IdimikangEventStore, normalize_event


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("VIBE_IDIMIKANG_DB_PATH", str(tmp_path / "idimikang.db"))
    import src.idimikang.store as store_module

    if store_module._store is not None:
        store_module._store.close()
    monkeypatch.setattr(store_module, "_store", None, raising=False)
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def test_normalize_idimikang_signal_marks_observer_only_and_taint() -> None:
    event = normalize_event(
        {
            "signal_id": "sig-1",
            "pair": "btcusdt",
            "ts": "2026-07-11T18:05:11Z",
            "side": "LONG",
            "score": "42.5",
            "reason_trace": {"regime": "ranging"},
        }
    )

    assert event["source"] == "idimikang"
    assert event["event_type"] == "market_signal"
    assert event["symbol"] == "BTCUSDT"
    assert event["direction"] == "long"
    assert event["score"] == 42.5
    assert event["features"]["reason_trace"]["regime"] == "ranging"
    assert event["provenance"]["observer_only"] is True
    assert event["provenance"]["execution_allowed"] is False
    assert event["provenance"]["tainted_window"] is True


def test_store_ingest_is_idempotent(tmp_path: Path) -> None:
    store = IdimikangEventStore(tmp_path / "idimikang.db")
    payload = {
        "source_event_id": "evt-1",
        "source": "idimikang",
        "event_type": "market_signal",
        "symbol": "ETHUSDT",
        "timestamp": "2026-07-12T00:00:00Z",
        "direction": "short",
        "score": 0.7,
    }

    first = store.ingest(payload)
    second = store.ingest(payload)

    assert first["inserted"] is True
    assert second["inserted"] is False
    events = store.list_events(symbol="ETHUSDT")
    assert len(events) == 1
    assert events[0]["provenance"]["observer_only"] is True
    store.close()


def test_idimikang_ingest_and_list_routes(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)

    response = client.post(
        "/data-sources/idimikang/ingest",
        json={
            "source": "idimikang",
            "event_type": "market_signal",
            "symbol": "BTCUSDT",
            "timestamp": "2026-07-11T18:05:11Z",
            "direction": "long",
            "score": 0.0,
            "timeframe": "unknown",
            "market_data": {},
            "features": {},
            "provenance": {"schema_version": "1.0"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["observer_only"] is True
    assert body["execution_allowed"] is False
    assert body["inserted"] == 1
    assert body["events"][0]["provenance"]["tainted_window"] is True

    listed = client.get("/data-sources/idimikang/events", params={"symbol": "BTCUSDT"})
    assert listed.status_code == 200
    events = listed.json()["events"]
    assert len(events) == 1
    assert events[0]["symbol"] == "BTCUSDT"


def test_idimikang_ingest_rejects_missing_symbol(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)

    response = client.post(
        "/data-sources/idimikang/ingest",
        json={"source": "idimikang", "event_type": "market_signal"},
    )

    assert response.status_code == 422
    assert "symbol" in response.json()["detail"]
