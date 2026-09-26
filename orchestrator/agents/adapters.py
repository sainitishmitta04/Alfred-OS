"""Wrap a plain `async def run_x_agent(goal: str) -> str` (the spec's interface) into an Agent."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable

from orchestrator.agents.base import Agent, AgentContext, AgentResult

AgentFn = Callable[..., Awaitable[str | AgentResult]]


class FunctionAgent(Agent):
    def __init__(self, name: str, description: str, fn: AgentFn, *, always_confirm: bool = False,
                 timeout_s: float | None = None) -> None:
        if not inspect.iscoroutinefunction(fn):
            raise TypeError(f"agent function for {name!r} must be `async def`")
        self.name, self.description, self._fn = name, description, fn
        self.always_confirm, self.timeout_s = always_confirm, timeout_s
        # Functions may optionally accept `ctx` to log steps.
        self._wants_ctx = len(inspect.signature(fn).parameters) >= 2

    async def run(self, goal: str, ctx: AgentContext) -> AgentResult | str:
        return await (self._fn(goal, ctx) if self._wants_ctx else self._fn(goal))


def agent_from_function(name: str, description: str, **kwargs) -> Callable[[AgentFn], FunctionAgent]:
    """Decorator form: `@agent_from_function("weather", "Weather questions")`."""
    return lambda fn: FunctionAgent(name, description, fn, **kwargs)
