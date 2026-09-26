from conftest import BROKEN, SLOW, FakeJev, StubRouter

from orchestrator.router import JevVerifier


async def test_happy_path(make_engine):
    e = make_engine(StubRouter("direct"))
    r = await e.handle_transcript("lower the volume")
    assert r["status"] == "completed" and r["route"] == "direct"
    assert r["response_text"].startswith("[MOCK] Direct")
    assert r["jev_latency_ms"] == 5 and r["agent_latency_ms"] is not None and r["latency_ms"] is not None
    actions = [s["action"] for s in r["steps"]]
    assert actions == ["route", "dispatch", "execute", "result"]


async def test_destructive_needs_confirmation_then_approve(make_engine):
    e = make_engine(StubRouter("desktop", destructive=True))
    r = await e.handle_transcript("delete my report")
    assert r["status"] == "needs_confirmation" and r["proposed_action"] == "delete my report"
    assert not any(s["action"] == "dispatch" for s in r["steps"])
    r2 = await e.confirm(r["session_id"], True)
    assert r2["status"] == "completed" and "Desktop" in r2["response_text"]
    again = await e.confirm(r["session_id"], True)  # idempotent
    assert again["status"] == "completed" and "nothing to confirm" in again["detail"]
    assert e.db.get_session(r["session_id"])["confirmed"] == 1


async def test_destructive_declined(make_engine):
    e = make_engine(StubRouter("desktop", destructive=True))
    r = await e.handle_transcript("delete my report")
    r2 = await e.confirm(r["session_id"], False)
    assert r2["status"] == "cancelled"
    assert not any(s["action"] == "dispatch" for s in r2["steps"])


async def test_confirm_unknown(make_engine):
    assert await make_engine().confirm("nope", True) is None


async def test_timeout_is_graceful(make_engine, registry):
    registry.register(SLOW)
    e = make_engine(StubRouter("slow"))
    r = await e.handle_transcript("do slow thing")
    assert r["status"] == "failed" and "too long" in r["response_text"]
    assert e.db.get_errors(r["session_id"])


async def test_agent_exception_is_graceful(make_engine, registry):
    registry.register(BROKEN)
    e = make_engine(StubRouter("broken"))
    r = await e.handle_transcript("x")
    assert r["status"] == "failed" and "kaboom" in e.db.get_errors(r["session_id"])[0]["message"]


async def test_router_exception_is_graceful(make_engine):
    class Boom:
        async def route(self, *a):
            raise RuntimeError("router down")
    r = await make_engine(Boom()).handle_transcript("x")
    assert r["status"] == "failed" and r["response_text"]


async def test_unknown_route(make_engine):
    r = await make_engine(StubRouter("ghost")).handle_transcript("x")
    assert r["status"] == "failed" and "ghost" in r["response_text"]


async def test_hooks_can_rewrite_goal_and_errors_are_isolated(make_engine):
    e = make_engine(StubRouter("browser"))
    e.add_hook("before_dispatch", lambda s: s.update(goal="cleaned goal"))
    e.add_hook("after_dispatch", lambda s: 1 / 0)
    r = await e.handle_transcript("uh, um, search news")
    assert r["status"] == "completed" and "cleaned goal" in r["response_text"]


async def test_always_confirm_agent(make_engine, registry):
    registry.get("knowledge").always_confirm = True
    try:
        r = await make_engine(StubRouter("knowledge")).handle_transcript("read notes")
        assert r["status"] == "needs_confirmation"
    finally:
        registry.get("knowledge").always_confirm = False


async def test_jev_verify_step(make_engine, settings):
    from dataclasses import replace
    e = make_engine(StubRouter("direct"), verifier=JevVerifier(FakeJev(satisfied=0.7)))
    e.settings = replace(settings, jev_verify=True)
    r = await e.handle_transcript("volume up")
    step = next(s for s in r["steps"] if s["action"] == "jev_verify")
    assert "0.70" in step["detail"] and step["success"] == 1


async def test_events_published(make_engine):
    e = make_engine(StubRouter("direct"))
    async with e.bus.subscribe() as q:
        await e.handle_transcript("volume up")
        types = [q.get_nowait()["type"] for _ in range(q.qsize())]
    assert types[0] == "session" and "step" in types and types[-1] == "status"
