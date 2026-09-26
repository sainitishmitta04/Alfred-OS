"""Connects the orchestrator to the desktop-use service (desktop-use/backend, Person C) over HTTP.

Plug in with:
    AGENT_OVERRIDES=desktop=desktop_agent:DesktopAgent,direct=desktop_agent:DirectAgent

The registry keys an agent by its class's `name`, not by the override key, so the `direct` route needs its
own class: `direct=desktop_agent:DesktopAgent` would only replace `desktop`, and "lower the volume" (which Jev
routes to `direct`) would still reach the mock.
"""

from __future__ import annotations

import json
import logging
import os

import httpx

from orchestrator.agents.base import Agent, AgentContext, AgentResult

log = logging.getLogger(__name__)


class DesktopAgent(Agent):
    name = "desktop"
    description = ("Mac control through AppleScript and local tools: opening or quitting apps, Finder and "
                   "listing local files, music playback (Spotify, Apple Music), volume, battery")

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.url = os.getenv("DESKTOP_AGENT_URL", "http://127.0.0.1:8787").rstrip("/")
        # The service runs up to 6 Haiku rounds; the default AGENT_TIMEOUT_S (10 s) is too short for that.
        self.timeout_s = float(os.getenv("DESKTOP_AGENT_TIMEOUT_S", "45"))
        self._transport = transport
        self._http: httpx.AsyncClient | None = None

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(base_url=self.url, transport=self._transport)
        return self._http

    async def startup(self) -> None:
        try:
            health = (await self._client().get("/health", timeout=3)).json()
            log.info("desktop agent at %s: anthropic=%s tools=%s", self.url,
                     health.get("anthropic_configured"), health.get("tools"))
        except Exception as exc:  # the service can start later; each run reports it clearly
            log.warning("desktop agent not reachable at %s: %s", self.url, exc)

    async def shutdown(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def run(self, goal: str, ctx: AgentContext) -> AgentResult:
        ctx.step("desktop_request", goal)
        try:
            # A second under the engine's timeout, so the user gets this agent's answer, not the generic one.
            r = await self._client().post("/api/v1/agent/execute", json={"message": goal},
                                          timeout=max(1.0, self.timeout_s - 1))
        except httpx.ConnectError:
            ctx.step("desktop_unreachable", self.url, False)
            return AgentResult(f"The desktop agent isn't running (expected at {self.url}).", success=False)
        except httpx.TimeoutException:
            ctx.step("desktop_timeout", f"no answer in {self.timeout_s - 1:.0f}s", False)
            return AgentResult("The desktop agent took too long, so I stopped waiting.", success=False)

        if r.status_code == 503:  # the service answers 503 when ANTHROPIC_API_KEY is missing
            ctx.step("desktop_not_configured", _detail(r), False)
            return AgentResult("The desktop agent isn't configured yet: it needs an Anthropic key.", success=False)
        if r.status_code >= 400:
            ctx.step("desktop_error", f"HTTP {r.status_code}: {_detail(r)}", False)
            return AgentResult("The desktop agent hit an error doing that.", success=False)

        body = r.json()
        results = body.get("tool_results") or []
        for t in results:
            result = str(t.get("result", ""))
            ctx.step(str(t.get("tool", "tool")), f"{json.dumps(t.get('input', {}), ensure_ascii=False)} → {result[:200]}",
                     '"error"' not in result)
        return AgentResult(body.get("summary") or "Done.",
                           data={"tool_results": results, "latency_ms": body.get("latency_ms")})


class DirectAgent(DesktopAgent):
    """Same service for one-shot native commands; the description is the `direct` mock's, so routing is unchanged."""

    name = "direct"
    description = ("A single trivial native OS action with no ambiguity, e.g. volume, "
                   "play/pause, brightness, locking the screen, opening a known app")


def _detail(r: httpx.Response) -> str:
    try:
        return str(r.json().get("detail", ""))[:200]
    except ValueError:
        return r.text[:200]
