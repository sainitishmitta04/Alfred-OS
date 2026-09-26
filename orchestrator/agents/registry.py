"""Agent registry + discovery. Three ways to plug an agent in, none of which touch the engine:

1. Built-ins: `orchestrator/agents/mocks.py` (and any module listed in BUILTIN_MODULES).
2. Pip entry points: group `alfred.agents`, e.g. in a teammate's pyproject:
       [project.entry-points."alfred.agents"]
       desktop = "desktop_agent:DesktopAgent"
3. Env override: AGENT_OVERRIDES="browser=browser_agent.main:run_browser_agent"
Later sources replace earlier ones by name, so a real agent cleanly shadows its mock.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Iterable
from importlib.metadata import entry_points
from typing import Any

from orchestrator.agents.adapters import FunctionAgent
from orchestrator.agents.base import Agent

log = logging.getLogger(__name__)

BUILTIN_MODULES = ["orchestrator.agents.mocks"]
ENTRY_POINT_GROUP = "alfred.agents"


class AgentRegistry:
    def __init__(self, agents: Iterable[Agent] = ()) -> None:
        self._agents: dict[str, Agent] = {}
        for agent in agents:
            self.register(agent)

    def register(self, agent: Agent) -> Agent:
        if not agent.name or not agent.description:
            raise ValueError(f"{agent!r} needs both a name and a description")
        if agent.name in self._agents:
            log.info("agent %r replaced by %r", agent.name, agent)
        self._agents[agent.name] = agent
        return agent

    def unregister(self, name: str) -> None:
        self._agents.pop(name, None)

    def get(self, name: str) -> Agent | None:
        return self._agents.get(name)

    def names(self) -> list[str]:
        return list(self._agents)

    def descriptions(self) -> dict[str, str]:
        return {name: agent.description for name, agent in self._agents.items()}

    def __iter__(self):
        return iter(self._agents.values())

    def __len__(self) -> int:
        return len(self._agents)

    def __contains__(self, name: object) -> bool:
        return name in self._agents

    # --- discovery --------------------------------------------------------------------------------
    @classmethod
    def discover(cls, overrides: dict[str, str] | None = None, *, entry_point_group: str = ENTRY_POINT_GROUP) -> "AgentRegistry":
        registry = cls()
        for module_name in BUILTIN_MODULES:
            module = importlib.import_module(module_name)
            for agent in getattr(module, "AGENTS", []):
                registry.register(agent)
        for ep in entry_points(group=entry_point_group):
            try:
                registry.register(_coerce(ep.load(), ep.name, registry))
            except Exception:  # a broken plugin must never take the engine down
                log.exception("failed to load agent entry point %r", ep.name)
        for name, target in (overrides or {}).items():
            try:
                registry.register(_coerce(load_object(target), name, registry))
            except Exception:
                log.exception("failed to load AGENT_OVERRIDES entry %s=%s", name, target)
        return registry


def load_object(target: str) -> Any:
    module_name, _, attr = target.partition(":")
    if not attr:
        raise ValueError(f"expected 'module:attr', got {target!r}")
    obj: Any = importlib.import_module(module_name)
    for part in attr.split("."):
        obj = getattr(obj, part)
    return obj


def _coerce(obj: Any, name: str, registry: AgentRegistry) -> Agent:
    """Accept an Agent instance, an Agent subclass, or a bare async function."""
    if isinstance(obj, type) and issubclass(obj, Agent):
        obj = obj()
    if isinstance(obj, Agent):
        if not obj.name:
            obj.name = name
        if not obj.description and (existing := registry.get(name)):
            obj.description = existing.description
        return obj
    if callable(obj):
        existing = registry.get(name)
        description = getattr(obj, "__doc__", None) or (existing.description if existing else "")
        return FunctionAgent(
            name, description.strip(), obj,
            always_confirm=existing.always_confirm if existing else False,
        )
    raise TypeError(f"cannot turn {obj!r} into an Agent")
