import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from browser_agent.agent import BrowserAgent, RunState
from browser_agent.config import BrowserSettings, MCPServerConfig, load_mcp_servers
from browser_agent.decisions import JevDecider, StepReview
from browser_agent.llm import ChatResult, LLMUnavailable, OpenRouterClient, ToolCall
from browser_agent.mcp_pool import MCPPool
from browser_agent.planner import parse_subtasks
from browser_agent.tools import ToolSpec, html_to_text
from orchestrator.agents.base import AgentContext, ConfirmationRequired


# --- fakes ----------------------------------------------------------------------------------------
class ScriptedLLM:
    """Returns queued ChatResults; records the messages it saw."""

    def __init__(self, *turns):
        self.turns, self.calls, self.models = list(turns), [], ["fake:free"]

    async def chat(self, messages, tools=None, **kw):
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools})
        if not self.turns:
            return ChatResult(content="fallback answer", model="fake:free")
        turn = self.turns.pop(0)
        if isinstance(turn, Exception):
            raise turn
        return turn


def calls(*specs):
    return ChatResult(content="", model="fake:free",
                      tool_calls=[ToolCall(id=f"c{i}_{name}", name=name, arguments=args) for i, (name, args) in enumerate(specs)])


class FakeDecider(JevDecider):
    def __init__(self, multi=0.1, risky=0.1, review=None):
        super().__init__(jev=None)
        self.multi, self.risky_score, self.review, self.risk_calls = multi, risky, review, []

    @property
    def enabled(self):
        return True

    async def is_multi_step(self, goal):
        return self.multi

    async def risky(self, goal, tool, arguments, page_hint=""):
        self.risk_calls.append(tool)
        return self.risky_score

    async def review_step(self, subtask, action, result_text):
        return self.review


def make_ctx():
    steps = []
    return AgentContext("s1", "browser", "t", None, lambda a, d=None, s=True: steps.append((a, d, s))), steps


async def _page(**kw):
    return "PAGE: Example Domain"


async def _click(target, **kw):
    return f"clicked {target}"


def agent_with(llm, decider=None, **settings):
    s = BrowserSettings(openrouter_api_key="k", max_steps=settings.pop("max_steps", 8), timeout_s=60, **settings)
    extra = [ToolSpec("browser_open", "open page", {"type": "object", "properties": {"url": {"type": "string"}}}, _page),
             ToolSpec("browser_click", "click", {"type": "object", "properties": {"target": {"type": "string"}}}, _click)]
    agent = BrowserAgent(s, llm=llm, decider=decider or FakeDecider(), pool=MCPPool([]), extra_tools=extra)
    return agent


# --- loop -----------------------------------------------------------------------------------------
async def test_single_task_tool_then_finish():
    llm = ScriptedLLM(calls(("browser_open", {"url": "https://example.com"})), calls(("finish", {"answer": "It says Example Domain."})))
    agent = agent_with(llm)
    ctx, steps = make_ctx()
    result = await agent.run("what does example.com say", ctx)
    assert result.success and result.text == "It says Example Domain."
    actions = [a for a, *_ in steps]
    assert actions[:3] == ["plan", "subtask", "think"] and "browser_open" in actions and "finish" in actions
    tool_msg = next(m for m in llm.calls[1]["messages"] if m["role"] == "tool")
    assert "Example Domain" in tool_msg["content"]


async def test_plain_content_is_answer():
    agent = agent_with(ScriptedLLM(ChatResult(content="Paris.", model="fake:free")))
    result = await agent.run("capital of france", make_ctx()[0])
    assert result.text == "Paris."


async def test_multi_chain_passes_results_forward():
    llm = ScriptedLLM(
        ChatResult(content='{"subtasks": ["find the top story", "summarize it"]}', model="p"),
        calls(("finish", {"answer": "Top story is X"})),
        calls(("finish", {"answer": "X is about Y"})),
        ChatResult(content="The top story X is about Y.", model="s"),
    )
    agent = agent_with(llm, FakeDecider(multi=0.9))
    ctx, steps = make_ctx()
    result = await agent.run("find the top story and then summarize it", ctx)
    assert result.text == "The top story X is about Y."
    assert [s["task"] for s in result.data["subtasks"]] == ["find the top story", "summarize it"]
    second_prompt = llm.calls[2]["messages"][1]["content"]
    assert "Top story is X" in second_prompt  # chaining context


async def test_risky_action_pauses_and_resumes():
    llm = ScriptedLLM(calls(("browser_click", {"target": "Submit order"})), calls(("finish", {"answer": "Order placed."})))
    decider = FakeDecider(risky=0.95)
    agent = agent_with(llm, decider)
    ctx, steps = make_ctx()
    with pytest.raises(ConfirmationRequired) as pause:
        await agent.run("buy it", ctx)
    state: RunState = pause.value.state
    assert "irreversible" in pause.value.prompt and state.pending_calls[0].name == "browser_click"
    result = await agent.resume(state, ctx)
    assert result.text == "Order placed."
    assert any(a == "browser_click" and s for a, _, s in steps)
    assert decider.risk_calls == ["browser_click"]  # approved call is not re-checked


async def test_read_only_tools_skip_risk_check():
    decider = FakeDecider(risky=0.99)
    llm = ScriptedLLM(calls(("browser_open", {"url": "x"})), calls(("finish", {"answer": "ok"})))
    await agent_with(llm, decider).run("open x", make_ctx()[0])
    assert decider.risk_calls == []


async def test_jev_done_review_adds_hint():
    review = StepReview(step_ok=0.95, progress="done", confidence=0.9, latency_ms=100)
    llm = ScriptedLLM(calls(("browser_open", {"url": "x"})), calls(("finish", {"answer": "ok"})))
    ctx, steps = make_ctx()
    await agent_with(llm, FakeDecider(review=review)).run("open x", ctx)
    assert any("call finish" in m["content"] for m in llm.calls[1]["messages"] if m["role"] == "user")
    assert any(a == "jev_review" for a, *_ in steps)


async def test_unknown_tool_and_bad_args_are_observations():
    bad = ChatResult(content="", model="m", tool_calls=[ToolCall("c1", "nope", {}), ToolCall("c2", "browser_open", {}, parse_error="invalid JSON")])
    llm = ScriptedLLM(bad, calls(("finish", {"answer": "recovered"})))
    result = await agent_with(llm).run("x", make_ctx()[0])
    assert result.text == "recovered"
    errors = [m["content"] for m in llm.calls[1]["messages"] if m["role"] == "tool"]
    assert all(e.startswith("ERROR") for e in errors) and len(errors) == 2


async def test_tool_exception_is_observation():
    async def boom(**kw):
        raise RuntimeError("page crashed")
    llm = ScriptedLLM(calls(("boom", {})), calls(("finish", {"answer": "handled"})))
    agent = agent_with(llm)
    agent._extra_tools.append(ToolSpec("boom", "b", {"type": "object", "properties": {}}, boom, read_only=True))
    result = await agent.run("x", make_ctx()[0])
    assert result.text == "handled"


async def test_step_limit_wraps_up():
    llm = ScriptedLLM(*[calls(("browser_open", {"url": "x"})) for _ in range(3)], ChatResult(content="partial answer", model="m"))
    ctx, steps = make_ctx()
    result = await agent_with(llm, max_steps=3).run("loop forever", ctx)
    assert not result.success and result.text == "partial answer"
    assert any(a == "budget" for a, *_ in steps)


async def test_llm_unavailable_is_graceful():
    result = await agent_with(ScriptedLLM(LLMUnavailable("down"))).run("x", make_ctx()[0])
    assert not result.success and "language model" in result.text


async def test_denylist_filters_tools():
    agent = agent_with(ScriptedLLM(), tool_denylist={"browser_click"})
    await agent.startup()
    assert "browser_click" not in agent.tools and "web_search" in agent.tools and "finish" in agent.tools


# --- LLM client -----------------------------------------------------------------------------------
class FakeCompletions:
    def __init__(self, behaviours):
        self.behaviours, self.models_called = behaviours, []

    async def create(self, **kw):
        self.models_called.append(kw["model"])
        b = self.behaviours[kw["model"]]
        if isinstance(b, Exception):
            raise b
        return b


def completion(content="", tool_calls=None):
    msg = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)], model="x")


async def test_openrouter_rotates_on_failure_and_cools_down():
    tc = SimpleNamespace(id="t1", function=SimpleNamespace(name="web_search", arguments='{"query": "q"}'))
    comp = FakeCompletions({"a:free": RuntimeError("429"), "b:free": completion(tool_calls=[tc])})
    client = OpenRouterClient("k", ["a:free", "b:free"], client=SimpleNamespace(chat=SimpleNamespace(completions=comp)))
    r = await client.chat([{"role": "user", "content": "hi"}])
    assert r.tool_calls[0].arguments == {"query": "q"} and comp.models_called == ["a:free", "b:free"]
    await client.chat([{"role": "user", "content": "hi"}])
    assert comp.models_called[-1] == "b:free" and comp.models_called.count("a:free") == 1  # a cooling down


async def test_openrouter_all_fail():
    comp = FakeCompletions({"a:free": RuntimeError("x"), "b:free": completion("")})
    client = OpenRouterClient("k", ["a:free", "b:free"], backoff_s=0.01, client=SimpleNamespace(chat=SimpleNamespace(completions=comp)))
    with pytest.raises(LLMUnavailable):
        await client.chat([{"role": "user", "content": "hi"}])


async def test_openrouter_bad_json_args_flagged():
    tc = SimpleNamespace(id="t1", function=SimpleNamespace(name="x", arguments="{not json"))
    comp = FakeCompletions({"a:free": completion(tool_calls=[tc])})
    client = OpenRouterClient("k", ["a:free"], client=SimpleNamespace(chat=SimpleNamespace(completions=comp)))
    r = await client.chat([])
    assert r.tool_calls[0].parse_error


# --- helpers & config -----------------------------------------------------------------------------
def test_parse_subtasks():
    assert parse_subtasks('Sure! {"subtasks": ["a", " b ", 3]}') == ["a", "b"]
    assert parse_subtasks("no json") == []


def test_html_to_text():
    assert html_to_text("<html><script>x()</script><p>Hello &amp; bye</p></html>") == "Hello & bye"


def test_load_mcp_servers(tmp_path, monkeypatch):
    cfg = tmp_path / "m.json"
    cfg.write_text('{"servers": {"a": {"command": "x", "args": ["--dir", "${T_DIR}"], "args_if_env": {"T_FLAG=true": ["--f"], "T_MISSING": ["--no"]}},'
                   ' "b": {"enabled_if_env": "T_MISSING", "command": "y"}, "c": {"enabled": false, "command": "z"}}}')
    monkeypatch.setenv("T_DIR", "/tmp/d")
    monkeypatch.setenv("T_FLAG", "TRUE")
    monkeypatch.delenv("T_MISSING", raising=False)
    servers = load_mcp_servers(cfg)
    assert [s.name for s in servers] == ["a"] and servers[0].args == ["--dir", "/tmp/d", "--f"]


def test_default_config_parses():
    servers = load_mcp_servers(Path(__file__).parent.parent / "mcp_servers.json")
    assert any(s.name == "playwright" for s in servers)


# --- real MCP round trip --------------------------------------------------------------------------
async def test_mcp_pool_real_stdio_server():
    server = Path(__file__).parent / "fake_mcp_server.py"
    pool = MCPPool([MCPServerConfig("fake", command=sys.executable, args=[str(server)], startup_timeout_s=30),
                    MCPServerConfig("broken", command="definitely-not-a-binary", startup_timeout_s=5)])
    await pool.start()
    try:
        assert pool.status["fake"].startswith("ok") and pool.status["broken"].startswith("failed")
        specs = {s.name: s for s in pool.tool_specs()}
        assert {"fake__echo", "fake__add"} <= set(specs)
        assert (await specs["fake__echo"].fn(text="hi")).text == "echo: hi"
        assert (await specs["fake__add"].fn(a=2, b=3)).text == "5"
        assert specs["fake__echo"].openai_schema()["function"]["parameters"]["properties"]
    finally:
        await pool.stop()


def test_describe_target_resolves_ref():
    from browser_agent.agent import describe_target
    page = '- textbox "Name" [ref=e5]\n- button "Submit order" [ref=e44]'
    assert 'Submit order' in describe_target({"target": "e44"}, page)
    assert describe_target({"target": "zzz"}, page) == ""


async def test_keyword_floor_pauses_even_if_jev_says_safe():
    page_llm = ScriptedLLM(calls(("browser_click", {"target": "e44"})))
    agent = agent_with(page_llm, FakeDecider(risky=0.05))
    ctx, _ = make_ctx()
    await agent.startup()
    state = RunState(goal="order", subtasks=["order"], last_page='- button "Submit order" [ref=e44]')
    state.messages = agent._initial_messages(state, "order")
    with pytest.raises(ConfirmationRequired) as pause:
        await agent._drive(state, ctx)
    assert "Submit order" in pause.value.prompt


async def test_openrouter_retries_rounds_after_all_fail():
    class Flaky:
        def __init__(self):
            self.n = 0

        async def create(self, **kw):
            self.n += 1
            if self.n <= 2:
                raise RuntimeError("429")
            return completion("hello")
    comp = Flaky()
    client = OpenRouterClient("k", ["a:free", "b:free"], backoff_s=0.01, client=SimpleNamespace(chat=SimpleNamespace(completions=comp)))
    assert (await client.chat([])).content == "hello" and comp.n == 3


async def test_daily_quota_fails_fast():
    from browser_agent.llm import DailyQuotaExceeded
    comp = FakeCompletions({"a:free": RuntimeError("Rate limit exceeded: free-models-per-day"), "b:free": completion("x")})
    client = OpenRouterClient("k", ["a:free", "b:free"], client=SimpleNamespace(chat=SimpleNamespace(completions=comp)))
    with pytest.raises(DailyQuotaExceeded):
        await client.chat([])
    assert comp.models_called == ["a:free"]
    result = await agent_with(ScriptedLLM(DailyQuotaExceeded("quota")), FakeDecider(multi=0.9)).run("a then b", make_ctx()[0])
    assert not result.success and "quota" in result.text


# --- multi-provider -------------------------------------------------------------------------------
async def test_router_falls_back_to_next_provider():
    from browser_agent.llm import GeminiClient, LLMRouter
    gem = FakeCompletions({"gemini-x": RuntimeError("429 RESOURCE_EXHAUSTED GenerateRequestsPerDayPerProjectPerModel-FreeTier")})
    orc = FakeCompletions({"a:free": completion("from openrouter")})
    gemini = GeminiClient("g", ["gemini-x"], backoff_s=0.01, client=SimpleNamespace(chat=SimpleNamespace(completions=gem)))
    openrouter = OpenRouterClient("o", ["a:free"], client=SimpleNamespace(chat=SimpleNamespace(completions=orc)))
    router = LLMRouter([gemini, openrouter])
    r = await router.chat([])
    assert r.content == "from openrouter" and r.model.startswith("openrouter:")
    assert gem.models_called == ["gemini-x"]  # per-day quota -> no retry rounds on that model
    await router.chat([])
    assert gem.models_called == ["gemini-x"]  # still cooling down, skipped straight to fallback


async def test_router_all_quota_raises_daily():
    from browser_agent.llm import DailyQuotaExceeded, GeminiClient, LLMRouter
    gem = FakeCompletions({"g1": RuntimeError("RequestsPerDay exceeded")})
    orc = FakeCompletions({"a:free": RuntimeError("free-models-per-day")})
    router = LLMRouter([GeminiClient("g", ["g1"], backoff_s=0.01, client=SimpleNamespace(chat=SimpleNamespace(completions=gem))),
                        OpenRouterClient("o", ["a:free"], client=SimpleNamespace(chat=SimpleNamespace(completions=orc)))])
    with pytest.raises(DailyQuotaExceeded):
        await router.chat([])


async def test_gemini_autopicks_newest_flash():
    from browser_agent.llm import GeminiClient
    ids = ["models/gemini-2.5-flash", "models/gemini-2.5-flash-lite", "models/gemini-3-flash-preview",
           "models/gemini-2.5-flash-image", "models/gemini-2.5-pro", "models/text-embedding-004", "models/gemini-2.0-flash-001"]
    models = SimpleNamespace(list=lambda: _aret(SimpleNamespace(data=[SimpleNamespace(id=i) for i in ids])))
    g = GeminiClient("k", None, client=SimpleNamespace(models=models, chat=None))
    assert await g.validate_models() == ["gemini-3-flash-preview", "gemini-2.5-flash", "gemini-2.5-flash-lite"]


async def _aret(v):
    return v


def test_build_llm_skips_providers_without_keys():
    from browser_agent.llm import build_llm
    s = BrowserSettings(gemini_api_key="g", openrouter_api_key="")
    router = build_llm(s)
    assert [p.provider for p in router.providers] == ["gemini"]
    with pytest.raises(ValueError):
        build_llm(BrowserSettings(gemini_api_key="", openrouter_api_key=""))


def test_provider_extra_fields_round_trip():
    tc = SimpleNamespace(id="t1", function=SimpleNamespace(name="nav", arguments="{}"),
                         model_extra={"extra_content": {"google": {"thought_signature": "SIG"}}})
    result = OpenRouterClient._parse(completion(tool_calls=[tc]), "m")
    msg = result.assistant_message()
    assert msg["tool_calls"][0]["extra_content"]["google"]["thought_signature"] == "SIG"


async def test_pre_approved_request_skips_first_risky_prompt_only():
    llm = ScriptedLLM(calls(("browser_click", {"target": "Submit"})), calls(("browser_click", {"target": "Pay now"})))
    agent = agent_with(llm, FakeDecider(risky=0.9))
    steps = []
    ctx = AgentContext("s1", "browser", "t", None, lambda a, d=None, s=True: steps.append(a), approved=True)
    with pytest.raises(ConfirmationRequired) as pause:
        await agent.run("submit and pay", ctx)
    assert "risk_pre_approved" in steps and "Pay now" in pause.value.prompt
