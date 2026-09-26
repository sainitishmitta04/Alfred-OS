from conftest import StubRouter

from orchestrator.agents import Agent, AgentResult, ConfirmationRequired


class PausingAgent(Agent):
    name, description = "pauser", "pauses mid-task"

    def __init__(self):
        self.cancelled = None

    async def run(self, goal, ctx):
        ctx.step("work", "half done")
        raise ConfirmationRequired("Submit the form?", {"progress": 1})

    async def resume(self, state, ctx):
        ctx.step("work", "finishing")
        return AgentResult(f"finished from {state['progress']}")

    async def cancel(self, state):
        self.cancelled = state


async def test_mid_task_pause_resume(make_engine, registry):
    registry.register(PausingAgent())
    e = make_engine(StubRouter("pauser"))
    r = await e.handle_transcript("fill the form")
    assert r["status"] == "needs_confirmation" and r["proposed_action"] == "Submit the form?"
    r2 = await e.confirm(r["session_id"], True)
    assert r2["status"] == "completed" and r2["response_text"] == "finished from 1"
    assert [s["action"] for s in r2["steps"]].count("resume") == 1


async def test_mid_task_pause_decline_calls_cancel(make_engine, registry):
    agent = registry.register(PausingAgent())
    e = make_engine(StubRouter("pauser"))
    r = await e.handle_transcript("fill the form")
    r2 = await e.confirm(r["session_id"], False)
    assert r2["status"] == "cancelled" and agent.cancelled == {"progress": 1}
