"""The `direct` route (one-shot native commands: volume, play/pause, opening an app) runs on the desktop agent.

Plug in with:  AGENT_OVERRIDES=direct=direct_agent:DIRECT

Jev routes "lower the volume" to `direct`, whose built-in agent is still a mock. This is an Agent instance rather
than the bare function because, for a function, the registry takes the function's docstring as the routing
description, which would replace direct's own.
"""

from desktop_use.orchestrator_agent import run_desktop_agent
from orchestrator.agents.adapters import FunctionAgent
from orchestrator.agents.mocks import AGENTS

DIRECT = FunctionAgent("direct", next(a.description for a in AGENTS if a.name == "direct"), run_desktop_agent,
                       timeout_s=120)
