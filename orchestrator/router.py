"""Routing: Jev (typed, fast) first; Claude forced-choice fallback when Jev is unsure; keywords when offline.

Every decision records which path produced it (`source`) and how long it took, so the UI can show
"Jev routed in 90ms" vs "Claude fallback in 700ms".
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from orchestrator.config import Settings

log = logging.getLogger(__name__)

ROUTE_QUESTION = "Which agent should handle this user request?"
DESTRUCTIVE_QUESTION = "Could carrying out this request overwrite or delete data, or be otherwise irreversible?"
DESTRUCTIVE_CRITERIA = {
    "true": "The request deletes, overwrites, moves, sends, posts, purchases or otherwise irreversibly changes something.",
    "false": "The request only reads, searches, opens, plays, adjusts a reversible setting, or creates something new.",
}


@dataclass
class RouteDecision:
    route: str
    confidence: float
    source: str                      # jev | claude_fallback | jev_low_confidence | keyword
    is_destructive: bool
    destructive_score: float | None = None
    latency_ms: int = 0
    probabilities: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


class Router(Protocol):
    async def route(self, transcript: str, agents: dict[str, str]) -> RouteDecision: ...


def _ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


# --- Jev ------------------------------------------------------------------------------------------
class JevClient:
    """Small wrapper over typesafe_sdk's AsyncTypeSafeClient so the rest of the code stays SDK-agnostic."""

    def __init__(self, api_key: str, timeout_s: float = 5.0, model: str | None = None, client: Any = None) -> None:
        if client is None:
            from typesafe_sdk import AsyncTypeSafeClient, RetryPolicy

            client = AsyncTypeSafeClient(api_key=api_key, timeout=timeout_s, model=model,
                                         retry=RetryPolicy(max_retries=1))
        self._client = client

    async def ask(self, state: Any, questions: dict[str, Any]) -> Any:
        return await self._client.system_one(state=state, questions=questions)

    async def aclose(self) -> None:
        close = getattr(self._client, "aclose", None)
        if close:
            await close()


class JevRouter:
    def __init__(self, jev: JevClient, destructive_threshold: float = 0.5) -> None:
        self.jev = jev
        self.destructive_threshold = destructive_threshold

    async def route(self, transcript: str, agents: dict[str, str]) -> RouteDecision:
        from typesafe_sdk import Choice, Noul

        start = time.perf_counter()
        result = await self.jev.ask(
            {"transcript": transcript},
            {
                "route": Choice(instructions=ROUTE_QUESTION, criteria=dict(agents)),
                "is_destructive": Noul(instructions=DESTRUCTIVE_QUESTION, criteria=DESTRUCTIVE_CRITERIA),
            },
        )
        route_answer = result.answers["route"]
        destructive = float(result.answers["is_destructive"].noul)
        probabilities = dict(route_answer.probabilities)
        return RouteDecision(
            route=route_answer.choice,
            confidence=float(probabilities.get(route_answer.choice, route_answer.confidence)),
            source="jev",
            is_destructive=destructive >= self.destructive_threshold,
            destructive_score=destructive,
            latency_ms=_ms(start),
            probabilities=probabilities,
        )


class JevVerifier:
    """Post-dispatch Jev check: did the agent's answer actually satisfy the goal? Logged as a step."""

    def __init__(self, jev: JevClient) -> None:
        self.jev = jev

    async def verify(self, goal: str, response_text: str) -> tuple[float, int]:
        from typesafe_sdk import Noul

        start = time.perf_counter()
        result = await self.jev.ask(
            {"user_goal": goal, "agent_response": response_text},
            {"goal_satisfied": Noul(
                instructions="Does the agent response indicate the user's goal was accomplished or answered?",
            )},
        )
        return float(result.answers["goal_satisfied"].noul), _ms(start)


# --- Claude fallback ------------------------------------------------------------------------------
class ClaudeRouter:
    """Small forced tool-choice call; only used when Jev is unsure or unavailable."""

    def __init__(self, api_key: str, model: str, client: Any = None, timeout_s: float = 8.0) -> None:
        if client is None:
            from anthropic import AsyncAnthropic

            client = AsyncAnthropic(api_key=api_key, timeout=timeout_s, max_retries=1)
        self.client, self.model = client, model

    async def route(self, transcript: str, agents: dict[str, str]) -> RouteDecision:
        start = time.perf_counter()
        options = "\n".join(f"- {name}: {desc}" for name, desc in agents.items())
        tool = {
            "name": "route_request",
            "description": "Pick the agent that should handle the user's spoken request.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "route": {"type": "string", "enum": list(agents)},
                    "is_destructive": {"type": "boolean", "description": DESTRUCTIVE_QUESTION},
                },
                "required": ["route", "is_destructive"],
            },
        }
        message = await self.client.messages.create(
            model=self.model,
            max_tokens=200,
            system=f"You route voice commands for a macOS assistant. Agents:\n{options}",
            messages=[{"role": "user", "content": transcript}],
            tools=[tool],
            tool_choice={"type": "tool", "name": "route_request"},
        )
        block = next(b for b in message.content if getattr(b, "type", None) == "tool_use")
        route = block.input["route"]
        if route not in agents:
            raise ValueError(f"Claude returned unknown route {route!r}")
        return RouteDecision(route=route, confidence=1.0, source="claude_fallback",
                             is_destructive=bool(block.input.get("is_destructive")), latency_ms=_ms(start))


# --- Offline keyword router -----------------------------------------------------------------------
_KEYWORDS: dict[str, tuple[str, ...]] = {
    "knowledge": ("note", "notes", "obsidian", "vault", "journal", "knowledge"),
    "browser": ("search", "google", "web", "website", "linkedin", "twitter", "online", "look up", "news", "browse"),
    "desktop": ("file", "files", "folder", "document", "pdf", "screenshot", "downloads", "desktop"),
    "direct": ("volume", "mute", "play", "pause", "brightness", "lock", "open", "launch"),
}
_DESTRUCTIVE_WORDS = re.compile(r"\b(delete|remove|erase|wipe|overwrite|replace|trash|rm|clear|format|send|post|drop)\b", re.I)


class KeywordRouter:
    """Last-resort, zero-network router so a demo never dead-ends."""

    async def route(self, transcript: str, agents: dict[str, str]) -> RouteDecision:
        start = time.perf_counter()
        text = transcript.lower()
        scores = {
            name: sum(1 for kw in _KEYWORDS.get(name, ()) if re.search(rf"\b{re.escape(kw)}\b", text))
            for name in agents
        }
        best = max(scores, key=lambda n: scores[n]) if scores else next(iter(agents))
        if scores.get(best, 0) == 0:
            best = "desktop" if "desktop" in agents else next(iter(agents))
        total = sum(scores.values()) or 1
        return RouteDecision(route=best, confidence=scores.get(best, 0) / total, source="keyword",
                             is_destructive=bool(_DESTRUCTIVE_WORDS.search(transcript)), latency_ms=_ms(start))


# --- Composite (the policy) -----------------------------------------------------------------------
class CompositeRouter:
    """Jev -> (confidence < threshold) Claude -> keyword. Never raises."""

    def __init__(self, jev: JevRouter | None, claude: ClaudeRouter | None, threshold: float = 0.6,
                 keyword: KeywordRouter | None = None) -> None:
        self.jev, self.claude, self.threshold = jev, claude, threshold
        self.keyword = keyword or KeywordRouter()

    async def route(self, transcript: str, agents: dict[str, str]) -> RouteDecision:
        start = time.perf_counter()
        notes: list[str] = []
        jev_decision: RouteDecision | None = None

        if self.jev:
            try:
                jev_decision = await self.jev.route(transcript, agents)
                if jev_decision.route in agents and jev_decision.confidence >= self.threshold:
                    return jev_decision
                notes.append(f"jev confidence {jev_decision.confidence:.2f} < {self.threshold} for {jev_decision.route!r}")
            except Exception as exc:
                log.warning("Jev routing failed: %s", exc)
                notes.append(f"jev error: {exc}")

        if self.claude:
            try:
                decision = await self.claude.route(transcript, agents)
                if jev_decision:  # Jev's destructive verdict is the typed signal — keep the stricter of the two
                    decision.is_destructive = decision.is_destructive or jev_decision.is_destructive
                    decision.destructive_score = jev_decision.destructive_score
                    decision.probabilities = jev_decision.probabilities
                decision.latency_ms, decision.notes = _ms(start), notes
                return decision
            except Exception as exc:
                log.warning("Claude fallback failed: %s", exc)
                notes.append(f"claude error: {exc}")

        if jev_decision and jev_decision.route in agents:
            jev_decision.source, jev_decision.latency_ms, jev_decision.notes = "jev_low_confidence", _ms(start), notes
            return jev_decision

        decision = await self.keyword.route(transcript, agents)
        decision.latency_ms, decision.notes = _ms(start), notes
        return decision


def build_router(settings: Settings, jev: JevClient | None) -> CompositeRouter:
    claude = ClaudeRouter(settings.anthropic_api_key, settings.fallback_model) if settings.anthropic_api_key else None
    return CompositeRouter(
        JevRouter(jev, settings.destructive_threshold) if jev else None,
        claude,
        settings.jev_confidence_threshold,
    )
