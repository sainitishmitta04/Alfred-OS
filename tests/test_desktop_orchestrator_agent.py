from unittest.mock import AsyncMock, patch

import pytest

from desktop_use.orchestrator_agent import run_desktop_agent
from orchestrator.agents.base import AgentContext
from orchestrator.config import Settings


def _ctx() -> AgentContext:
    settings = Settings(anthropic_api_key="test-key")
    steps: list[tuple[str, str | None, bool | None]] = []

    def log_step(action: str, detail: str | None = None, success: bool | None = True) -> None:
        steps.append((action, detail, success))

    return AgentContext(
        session_id="s1",
        agent="desktop",
        transcript="list my downloads",
        settings=settings,
        _log_step=log_step,
    )


@pytest.mark.asyncio
async def test_run_desktop_agent_delegates_to_engine():
    ctx = _ctx()
    fake_outcome = {
        "summary": "Listed 3 files.",
        "tool_results": [{"tool": "list_directory", "input": {}, "result": "{}"}],
        "latency_ms": 42,
    }
    with patch("desktop_use.agent.engine.AgentEngine") as engine_cls:
        engine_cls.return_value.run = AsyncMock(return_value=fake_outcome)
        result = await run_desktop_agent("list files in Downloads", ctx)

    assert result.text == "Listed 3 files."
    assert result.success is True
    assert result.data["latency_ms"] == 42
    engine_cls.return_value.run.assert_awaited_once()
