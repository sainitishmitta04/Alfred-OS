import json

import httpx
from conftest import StubRouter

from desktop_agent import DesktopAgent, DirectAgent
from orchestrator.agents import AgentRegistry


def transport(handler):
    return httpx.MockTransport(handler)


def ok_service(request: httpx.Request) -> httpx.Response:
    assert request.url.path == "/api/v1/agent/execute"
    assert json.loads(request.content) == {"message": "lower the volume"}
    return httpx.Response(200, json={
        "summary": "Volume set to 30%.",
        "tool_results": [{"tool": "execute_system_script", "input": {"command_type": "set_volume", "args": {"level": 30}},
                          "result": json.dumps({"ok": True, "volume": 30})}],
        "latency_ms": 900,
    })


async def test_direct_route_runs_on_the_desktop_service(make_engine, registry):
    registry.register(DirectAgent(transport=transport(ok_service)))
    r = await make_engine(StubRouter("direct")).handle_transcript("lower the volume")
    assert r["status"] == "completed" and r["response_text"] == "Volume set to 30%."
    tool_steps = [s for s in r["steps"] if s["action"] == "execute_system_script"]
    assert tool_steps and tool_steps[0]["success"] == 1 and "set_volume" in tool_steps[0]["detail"]


async def test_service_down_is_a_clear_failure(make_engine, registry):
    def refuse(request):
        raise httpx.ConnectError("connection refused")
    registry.register(DesktopAgent(transport=transport(refuse)))
    r = await make_engine(StubRouter("desktop")).handle_transcript("open Safari")
    assert r["status"] == "failed" and "isn't running" in r["response_text"]


async def test_missing_anthropic_key_is_reported(make_engine, registry):
    registry.register(DesktopAgent(transport=transport(
        lambda req: httpx.Response(503, json={"detail": "ANTHROPIC_API_KEY is not set"}))))
    r = await make_engine(StubRouter("desktop")).handle_transcript("open Safari")
    assert r["status"] == "failed" and "Anthropic key" in r["response_text"]
    assert any(s["action"] == "desktop_not_configured" for s in r["steps"])


async def test_tool_error_marks_the_step_failed(make_engine, registry):
    registry.register(DesktopAgent(transport=transport(lambda req: httpx.Response(200, json={
        "summary": "I couldn't do that.",
        "tool_results": [{"tool": "control_media_player", "input": {"action": "play"},
                          "result": json.dumps({"error": "Spotify is not running"})}]}))))
    r = await make_engine(StubRouter("desktop")).handle_transcript("play music")
    step = next(s for s in r["steps"] if s["action"] == "control_media_player")
    assert step["success"] == 0


def test_overrides_replace_both_mocks():
    reg = AgentRegistry.discover({"desktop": "desktop_agent:DesktopAgent", "direct": "desktop_agent:DirectAgent"})
    assert isinstance(reg.get("desktop"), DesktopAgent) and isinstance(reg.get("direct"), DirectAgent)
    assert reg.get("direct").description.startswith("A single trivial native OS action")
