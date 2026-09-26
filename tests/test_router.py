from types import SimpleNamespace

from conftest import FakeJev

from orchestrator.agents.mocks import AGENTS
from orchestrator.router import CompositeRouter, JevRouter, JevVerifier, KeywordRouter

AGENT_DESC = {a.name: a.description for a in AGENTS}


class FakeClaude:
    def __init__(self, route="browser", destructive=False, fail=False):
        self.pick, self.destructive, self.fail, self.calls = route, destructive, fail, 0

    async def route(self, transcript, agents):
        from orchestrator.router import RouteDecision
        self.calls += 1
        if self.fail:
            raise RuntimeError("no network")
        return RouteDecision(self.pick, 1.0, "claude_fallback", self.destructive)


async def test_jev_confident_wins():
    r = CompositeRouter(JevRouter(FakeJev("direct", {"direct": 0.9, "browser": 0.1})), FakeClaude(), 0.6)
    d = await r.route("lower the volume", AGENT_DESC)
    assert (d.route, d.source, d.is_destructive) == ("direct", "jev", False)


async def test_low_confidence_falls_back_to_claude_keeping_jev_destructive():
    claude = FakeClaude("desktop", destructive=False)
    r = CompositeRouter(JevRouter(FakeJev("browser", {"browser": 0.4, "desktop": 0.35}, destructive=0.9)), claude, 0.6)
    d = await r.route("clean up stuff", AGENT_DESC)
    assert (d.route, d.source, d.is_destructive) == ("desktop", "claude_fallback", True)
    assert claude.calls == 1 and d.notes


async def test_low_confidence_without_claude_uses_jev_pick():
    r = CompositeRouter(JevRouter(FakeJev("browser", {"browser": 0.4})), None, 0.6)
    d = await r.route("hmm", AGENT_DESC)
    assert (d.route, d.source) == ("browser", "jev_low_confidence")


async def test_everything_down_uses_keywords():
    r = CompositeRouter(JevRouter(FakeJev(error=RuntimeError("down"))), FakeClaude(fail=True), 0.6)
    d = await r.route("delete the file in downloads", AGENT_DESC)
    assert (d.route, d.source, d.is_destructive) == ("desktop", "keyword", True)


async def test_keyword_router_routes():
    k = KeywordRouter()
    assert (await k.route("open my obsidian notes", AGENT_DESC)).route == "desktop"
    assert (await k.route("search linkedin posts", AGENT_DESC)).route == "browser"
    assert (await k.route("mute the volume", AGENT_DESC)).route == "direct"


async def test_verifier():
    score, ms = await JevVerifier(FakeJev(satisfied=0.8)).verify("goal", "done")
    assert score == 0.8 and ms >= 0


async def test_claude_router_parses_tool_use():
    from orchestrator.router import ClaudeRouter

    class Msgs:
        async def create(self, **kw):
            assert kw["tool_choice"]["name"] == "route_request"
            return SimpleNamespace(content=[SimpleNamespace(type="tool_use", input={"route": "desktop", "is_destructive": False})])

    d = await ClaudeRouter("k", "m", client=SimpleNamespace(messages=Msgs())).route("notes", AGENT_DESC)
    assert (d.route, d.source) == ("desktop", "claude_fallback")
