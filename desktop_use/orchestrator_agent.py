from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from orchestrator.agents.base import AgentContext, AgentResult

DESKTOP_AGENT_DESCRIPTION = (
    "Requires local file read/search/write/move/delete, listing folders, screenshots, "
    "media control, volume/battery checks, or app actions tied to local files — not general web browsing."
)


def _tool_step_logger(ctx: AgentContext) -> Callable[[str, dict[str, Any], dict[str, Any]], None]:
    def log(tool: str, tool_input: dict[str, Any], payload: dict[str, Any]) -> None:
        detail = tool_input if tool_input else None
        success = "error" not in payload
        ctx.step(tool, str(detail) if detail is not None else None, success)

    return log


async def run_desktop_agent(goal: str, ctx: AgentContext) -> AgentResult:
    """Orchestrator entry: Haiku chooses tools and runs filesystem + native desktop actions."""
    from desktop_use.agent.engine import AgentEngine

    ctx.step("plan", goal)
    api_key = getattr(ctx.settings, "anthropic_api_key", "") or None
    model = os.getenv("ALFRED_AGENT_MODEL", "claude-3-5-haiku-20241022").strip()

    engine = AgentEngine(api_key=api_key, model=model or None)
    try:
        outcome = await engine.run(goal, on_tool=_tool_step_logger(ctx))
    except (ValueError, RuntimeError) as error:
        ctx.step("error", str(error), False)
        return AgentResult(text=str(error), success=False)

    summary = outcome.get("summary", "Done.")
    success = not any(
        "error" in str(item.get("result", ""))
        for item in outcome.get("tool_results", [])
    )
    return AgentResult(
        text=summary,
        success=success,
        data={
            "tool_results": outcome.get("tool_results", []),
            "latency_ms": outcome.get("latency_ms"),
        },
    )
