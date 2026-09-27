"""The desktop engine must not accept 'I'll do it' with no tool call — it nudges the model to actually act."""

from __future__ import annotations

import sys
import types
from unittest.mock import patch

import pytest

from desktop_use.agent.engine import AgentEngine


def _block(**kw):
    return types.SimpleNamespace(**kw)


class FakeMessages:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class FakeAnthropic:
    def __init__(self, responses):
        self.messages = FakeMessages(responses)


def _run(engine):
    import asyncio
    return asyncio.run(engine.run("open VS Code and make a note"))


@pytest.fixture
def anthropic_module(monkeypatch):
    """Stub `from anthropic import AsyncAnthropic` inside engine.run with a scripted client."""
    holder = {}
    mod = types.ModuleType("anthropic")
    mod.AsyncAnthropic = lambda **_: holder["client"]
    monkeypatch.setitem(sys.modules, "anthropic", mod)
    return holder


def test_narrating_first_turn_is_nudged_then_acts(anthropic_module):
    # Turn 1: text only, no tool call (the bug). Turn 2 (after the nudge): a real tool call. Turn 3: done.
    narrate = _block(stop_reason="end_turn", content=[_block(type="text", text="I'll open VS Code now.")])
    act = _block(stop_reason="tool_use", content=[
        _block(type="tool_use", id="t1", name="write_file", input={"path": "/tmp/a.md", "content": "hi"})])
    done = _block(stop_reason="end_turn", content=[_block(type="text", text="Created the file.")])
    anthropic_module["client"] = FakeAnthropic([narrate, act, done])

    engine = AgentEngine(api_key="k", model="claude-haiku-4-5")
    with patch("desktop_use.agent.engine.TOOL_HANDLERS", {"write_file": _fake_write}):
        result = _run(engine)

    assert result["tool_results"], "the nudge should have produced a real tool call"
    assert result["tool_results"][0]["tool"] == "write_file"
    assert result["summary"] == "Created the file."


def test_nudge_happens_only_once(anthropic_module):
    # Model narrates twice and never acts: engine nudges once, then returns rather than looping forever.
    narrate = _block(stop_reason="end_turn", content=[_block(type="text", text="I will do it.")])
    anthropic_module["client"] = FakeAnthropic([narrate, narrate])
    engine = AgentEngine(api_key="k", model="claude-haiku-4-5")
    result = _run(engine)
    assert result["tool_results"] == []
    assert result["summary"] == "I will do it."
    assert len(anthropic_module["client"].messages.calls) == 2  # one nudge, then it gives up


async def _fake_write(**_):
    return {"ok": True}
