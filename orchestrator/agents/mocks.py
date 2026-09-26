"""Default agents. Each is a MOCK — replace with the real implementation via AGENT_OVERRIDES or an entry point.

The descriptions are the routing criteria Jev sees, so keep them precise when you swap in a real agent.
"""

from __future__ import annotations

import asyncio

from desktop_use.orchestrator_agent import DESKTOP_AGENT_DESCRIPTION, run_desktop_agent
from orchestrator.agents.adapters import FunctionAgent
from orchestrator.agents.base import AgentContext


# MOCK — replace with real import (Person B: Browser Agent, Playwright MCP + Brave Search MCP)
async def run_browser_agent(goal: str, ctx: AgentContext) -> str:
    ctx.step("search", f"would search the web for: {goal}")
    await asyncio.sleep(0.5)
    return f"[MOCK] Browser agent would handle: {goal}"


# MOCK — replace with real import (Person A: Knowledge Agent, Obsidian MCP)
async def run_knowledge_agent(goal: str, ctx: AgentContext) -> str:
    ctx.step("vault_search", f"would search the Obsidian vault for: {goal}")
    await asyncio.sleep(0.3)
    return f"[MOCK] Knowledge agent would handle: {goal}"


# MOCK — replace with real native executor (volume, play/pause, open app)
async def run_direct_command(goal: str, ctx: AgentContext) -> str:
    ctx.step("execute", goal)
    await asyncio.sleep(0.1)
    return f"[MOCK] Direct command executed: {goal}"


AGENTS = [
    FunctionAgent("direct", "A single trivial native OS action with no ambiguity, e.g. volume, "
                  "play/pause, brightness, locking the screen, opening a known app", run_direct_command),
    FunctionAgent("browser", "Requires live website interaction — web search, social media, "
                  "forms, looking things up or reading pages online", run_browser_agent),
    FunctionAgent(
        "desktop",
        DESKTOP_AGENT_DESCRIPTION,
        run_desktop_agent,
        timeout_s=120,
    ),
    FunctionAgent("knowledge", "Refers to the user's notes, the Obsidian vault, or personal "
                  "knowledge base (reading, writing, or searching notes)", run_knowledge_agent),
]
