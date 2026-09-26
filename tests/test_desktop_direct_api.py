from fastapi.testclient import TestClient

from orchestrator.main import create_app


def test_desktop_run_endpoint(make_engine):
    engine = make_engine()
    with TestClient(create_app(engine)) as client:
        response = client.post("/agents/desktop/run", json={"command": "list downloads"})
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert "Desktop" in body["summary"]
        assert any(step["action"] == "plan" for step in body["steps"])
