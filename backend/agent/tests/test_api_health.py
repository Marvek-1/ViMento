from __future__ import annotations

from fastapi.testclient import TestClient

import api_server


def test_health_contract_is_available_without_authentication() -> None:
    response = TestClient(api_server.app, client=("127.0.0.1", 50000)).get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] in {"healthy", "degraded"}
    assert payload["service"] == "Vibe-Trading API"
    assert payload["timestamp"]
