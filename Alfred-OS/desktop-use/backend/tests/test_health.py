from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_ok() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "alfred"
    assert "platform" in payload
    assert isinstance(payload["anthropic_configured"], bool)
    assert isinstance(payload["playwright_available"], bool)
    assert payload["tools"] == [
        "control_media_player",
        "execute_system_script",
        "headless_web_scrape",
    ]
