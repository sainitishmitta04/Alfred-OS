from desktop_use.orchestrator_agent import run_desktop_agent
from orchestrator.agents import AgentRegistry


def test_direct_route_runs_the_desktop_agent_with_its_own_description():
    reg = AgentRegistry.discover({"direct": "direct_agent:DIRECT"})
    direct = reg.get("direct")
    assert direct._fn is run_desktop_agent and direct.timeout_s == 120
    assert direct.description.startswith("A single trivial native OS action")  # routing unchanged
    assert reg.get("desktop").description != direct.description
