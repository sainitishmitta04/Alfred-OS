from conftest import StubRouter
from fastapi.testclient import TestClient

from orchestrator.main import create_app


def test_api_flow(make_engine):
    engine = make_engine(StubRouter("desktop", destructive=True))
    with TestClient(create_app(engine)) as c:
        assert c.get("/health").json()["status"] == "ok"
        assert {a["name"] for a in c.get("/agents").json()} >= {"browser", "desktop"}
        r = c.post("/transcript", json={"transcript": "delete old logs"}).json()
        assert r["status"] == "needs_confirmation"
        r2 = c.post("/confirm", json={"session_id": r["session_id"], "approved": True}).json()
        assert r2["status"] == "completed"
        s = c.get(f"/sessions/{r['session_id']}").json()
        assert s["confirmed"] == 1 and s["steps"] and s["errors"] == []
        assert c.get(f"/sessions/{r['session_id']}/steps").json()
        assert c.get("/sessions").json()[0]["id"] == r["session_id"]
        assert c.get("/sessions/missing").status_code == 404
        assert c.post("/confirm", json={"session_id": "missing", "approved": True}).status_code == 404
        assert c.post("/transcript", json={"transcript": ""}).status_code == 422
