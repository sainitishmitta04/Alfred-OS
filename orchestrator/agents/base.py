"""The contract every Alfred agent implements. This is the only file a teammate needs to read."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentResult:
    text: str                      # spoken-friendly response
    success: bool = True
    data: dict[str, Any] = field(default_factory=dict)


StepLogger = Callable[[str, "str | None", "bool | None"], None]


@dataclass
class AgentContext:
    """Handed to `Agent.run`. Call `ctx.step(...)` for each action so it shows in the live UI log."""

    session_id: str
    agent: str
    transcript: str
    settings: Any
    _log_step: StepLogger

    def step(self, action: str, detail: str | None = None, success: bool | None = True) -> None:
        self._log_step(action, detail, success)


class Agent(ABC):
    """Subclass, set `name` + `description`, implement `run`. The description is what Jev routes on."""

    name: str = ""
    description: str = ""
    # True = every request to this agent needs user confirmation, regardless of Jev's verdict.
    always_confirm: bool = False
    # Per-agent timeout override (seconds); None uses AGENT_TIMEOUT_S.
    timeout_s: float | None = None

    @abstractmethod
    async def run(self, goal: str, ctx: AgentContext) -> AgentResult | str: ...

    async def startup(self) -> None:
        """Optional: open MCP sessions, browsers, etc. Called once when the server starts."""

    async def shutdown(self) -> None:
        """Optional: release resources."""

    def __repr__(self) -> str:
        return f"<Agent {self.name}>"
