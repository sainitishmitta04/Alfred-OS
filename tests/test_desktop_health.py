from __future__ import annotations

from fastapi.testclient import TestClient

from desktop_use.main import app


def test_health_returns_ok() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "alfred"
    assert "read_file" in payload["tools"]
    assert "control_media_player" in payload["tools"]
