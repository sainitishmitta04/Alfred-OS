import time

from conftest import SLOW, StubRouter
from fastapi.testclient import TestClient

from orchestrator.main import create_app


def wait_for_status(client, session_id, wanted, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = client.get(f"/sessions/{session_id}")
        if r.status_code == 200 and r.json()["status"] in wanted:
            return r.json()
        time.sleep(0.02)
    raise AssertionError(f"session {session_id} never reached {wanted}")


def test_task_answers_before_the_agent_finishes(make_engine, registry):
    registry.register(SLOW)  # sleeps 5 s; the test settings time agents out after 1 s
    with TestClient(create_app(make_engine(StubRouter("slow")))) as c:
        t0 = time.monotonic()
        r = c.post("/tasks", json={"transcript": "take your time"})
        assert r.status_code == 202 and time.monotonic() - t0 < 0.5
        session_id = r.json()["session_id"]
        assert wait_for_status(c, session_id, {"failed"})["response_text"].startswith("Sorry, that took too long")


def test_background_confirmation(make_engine):
    with TestClient(create_app(make_engine(StubRouter("desktop", destructive=True)))) as c:
        session_id = c.post("/tasks", json={"transcript": "delete old logs"}).json()["session_id"]
        wait_for_status(c, session_id, {"needs_confirmation"})
        r = c.post(f"/tasks/{session_id}/confirm", json={"approved": True})
        assert r.status_code == 202
        assert wait_for_status(c, session_id, {"completed"})["confirmed"] == 1
        assert c.post(f"/tasks/{session_id}/confirm", json={"approved": True}).status_code == 409
        assert c.post("/tasks/missing/confirm", json={"approved": True}).status_code == 404


def test_background_decline(make_engine):
    with TestClient(create_app(make_engine(StubRouter("desktop", destructive=True)))) as c:
        session_id = c.post("/tasks", json={"transcript": "delete old logs"}).json()["session_id"]
        wait_for_status(c, session_id, {"needs_confirmation"})
        c.post(f"/tasks/{session_id}/confirm", json={"approved": False})
        assert wait_for_status(c, session_id, {"cancelled"})["response_text"] == "Okay, I won't do that."
