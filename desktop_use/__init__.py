"""Desktop agent: Haiku tool loop, filesystem + native tools, orchestrator adapter."""

from desktop_use.agent.engine import AgentEngine
from desktop_use.orchestrator_agent import DESKTOP_AGENT_DESCRIPTION, run_desktop_agent

__all__ = ["AgentEngine", "DESKTOP_AGENT_DESCRIPTION", "run_desktop_agent"]
