from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from orchestrator.agents import AgentRegistry, FunctionAgent
from orchestrator.agents.mocks import AGENTS
from orchestrator.config import Settings
from orchestrator.db import Database
from orchestrator.engine import Orchestrator
from orchestrator.router import RouteDecision


class StubRouter:
    """Returns a fixed decision; records calls."""

    def __init__(self, route: str = "direct", destructive: bool = False, confidence: float = 0.9) -> None:
        self.decision = RouteDecision(route=route, confidence=confidence, source="jev",
                                      is_destructive=destructive, destructive_score=0.9 if destructive else 0.1,
                                      latency_ms=5)
        self.calls: list[str] = []

    async def route(self, transcript, agents):
        self.calls.append(transcript)
        return self.decision


class FakeJev:
    """Mimics typesafe_sdk responses: `.answers[name]` with .choice/.probabilities/.confidence/.noul."""

    def __init__(self, route="direct", probs=None, destructive=0.1, satisfied=0.9, error: Exception | None = None):
        self.route, self.probs = route, probs or {route: 0.95}
        self.destructive, self.satisfied, self.error = destructive, satisfied, error
        self.calls = 0

    async def ask(self, state, questions):
        self.calls += 1
        if self.error:
            raise self.error
        answers = {}
        if "route" in questions:
            answers["route"] = SimpleNamespace(choice=self.route, probabilities=self.probs,
                                               confidence=self.probs[self.route])
        if "is_destructive" in questions:
            answers["is_destructive"] = SimpleNamespace(noul=self.destructive)
        if "goal_satisfied" in questions:
            answers["goal_satisfied"] = SimpleNamespace(noul=self.satisfied)
        return SimpleNamespace(answers=answers)


@pytest.fixture
def settings() -> Settings:
    return Settings(db_path=":memory:", agent_timeout_s=1.0, jev_verify=False)


@pytest.fixture
def db() -> Database:
    return Database(":memory:")


@pytest.fixture
def registry() -> AgentRegistry:
    return AgentRegistry(AGENTS)


@pytest.fixture
def make_engine(settings, db, registry):
    def _make(router=None, **kw) -> Orchestrator:
        return Orchestrator(settings, db, registry, router or StubRouter(), **kw)
    return _make


async def slow_agent(goal: str) -> str:
    await asyncio.sleep(5)
    return "never"


async def broken_agent(goal: str) -> str:
    raise RuntimeError("kaboom")


SLOW = FunctionAgent("slow", "slow agent", slow_agent)
BROKEN = FunctionAgent("broken", "broken agent", broken_agent)
