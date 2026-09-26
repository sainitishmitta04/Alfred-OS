import sys
import types

import pytest

from orchestrator.agents import Agent, AgentRegistry, AgentResult, FunctionAgent


def test_discover_builtins():
    r = AgentRegistry.discover()
    assert set(r.names()) >= {"direct", "browser", "desktop"}
    assert "knowledge" not in r.names()  # note requests go to the desktop agent


def test_override_with_function_and_class():
    mod = types.ModuleType("fake_team_agents")

    async def run_browser_agent(goal: str) -> str:
        return f"real browser: {goal}"

    class Weather(Agent):
        name, description = "weather", "Weather forecasts"

        async def run(self, goal, ctx):
            return AgentResult("sunny")

    mod.run_browser_agent, mod.Weather = run_browser_agent, Weather
    sys.modules["fake_team_agents"] = mod
    try:
        r = AgentRegistry.discover({"browser": "fake_team_agents:run_browser_agent",
                                    "weather": "fake_team_agents:Weather",
                                    "broken": "nope.module:x"})
    finally:
        del sys.modules["fake_team_agents"]
    assert isinstance(r.get("browser"), FunctionAgent) and "website" in r.get("browser").description
    assert r.get("weather").description == "Weather forecasts"
    assert "broken" not in r  # bad override is logged, not fatal


def test_requires_description():
    async def f(goal): return ""
    with pytest.raises(ValueError):
        AgentRegistry([FunctionAgent("x", "", f)])


def test_sync_function_rejected():
    with pytest.raises(TypeError):
        FunctionAgent("x", "y", lambda goal: "")
