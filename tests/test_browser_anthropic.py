from types import SimpleNamespace

import pytest

from browser_agent.config import BrowserSettings
from browser_agent.llm import AnthropicClient, LLMUnavailable, OpenAICompatClient, _to_anthropic, build_llm

TOOLS = [{"type": "function", "function": {"name": "fetch_url", "description": "Fetch a page",
                                           "parameters": {"type": "object", "properties": {"url": {"type": "string"}}}}}]


class Block(SimpleNamespace):
    def model_dump(self, **_):
        return dict(vars(self))


class FakeMessages:
    def __init__(self, response):
        self.response, self.calls = response, []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def fake_client(content, stop_reason="tool_use"):
    return SimpleNamespace(messages=FakeMessages(SimpleNamespace(content=content, stop_reason=stop_reason, model="claude-opus-5")))


def test_history_conversion_merges_tool_results_into_one_user_turn():
    system, turns = _to_anthropic([
        {"role": "system", "content": "You browse."},
        {"role": "user", "content": "latest python?"},
        {"role": "assistant", "content": "", "tool_calls": [  # made by another provider earlier in the run
            {"id": "call_0", "type": "function", "function": {"name": "fetch_url", "arguments": '{"url": "https://python.org"}'}}]},
        {"role": "tool", "tool_call_id": "call_0", "content": "Python 3.14.7"},
        {"role": "user", "content": "Check: call finish."},
    ])
    assert system == "You browse."
    assert [t["role"] for t in turns] == ["user", "assistant", "user"]
    assert turns[1]["content"] == [{"type": "tool_use", "id": "call_0", "name": "fetch_url", "input": {"url": "https://python.org"}}]
    assert [b["type"] for b in turns[2]["content"]] == ["tool_result", "text"]  # results first, then the hint


async def test_claude_reply_round_trips_with_its_thinking_block():
    thinking = Block(type="thinking", thinking="", signature="sig")
    call = Block(type="tool_use", id="toolu_1", name="fetch_url", input={"url": "https://python.org"})
    client = fake_client([thinking, call])
    llm = AnthropicClient("k", client=client)

    result = await llm.chat([{"role": "user", "content": "latest python?"}], TOOLS)
    sent = client.messages.calls[0]
    assert sent["model"] == "claude-opus-5" and sent["output_config"] == {"effort": "low"}
    assert "temperature" not in sent  # current Claude models reject sampling parameters
    assert sent["tools"][0]["input_schema"]["properties"] == {"url": {"type": "string"}}
    assert result.tool_calls[0].name == "fetch_url" and result.tool_calls[0].arguments == {"url": "https://python.org"}

    # Next turn: the assistant message goes back exactly as Claude sent it, thinking block included.
    history = [{"role": "user", "content": "latest python?"}, result.assistant_message(),
               {"role": "tool", "tool_call_id": "toolu_1", "content": "Python 3.14.7"}]
    _, turns = _to_anthropic(history)
    assert turns[1]["content"][0] == {"type": "thinking", "thinking": "", "signature": "sig"}


async def test_refusal_falls_through_to_the_next_provider():
    llm = AnthropicClient("k", client=fake_client([], stop_reason="refusal"))
    with pytest.raises(LLMUnavailable, match="declined"):
        await llm.chat([{"role": "user", "content": "x"}])


async def test_openrouter_style_providers_never_see_the_private_field():
    seen = {}

    class Completions:
        async def create(self, **kwargs):
            seen.update(kwargs)
            msg = SimpleNamespace(content="ok", tool_calls=None)
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)], model="m")

    llm = OpenAICompatClient("k", ["m"], base_url="x", client=SimpleNamespace(chat=SimpleNamespace(completions=Completions())))
    await llm.chat([{"role": "assistant", "content": "hi", "_anthropic_content": [{"type": "text", "text": "hi"}]}])
    assert "_anthropic_content" not in seen["messages"][0]


def test_anthropic_is_first_when_listed_first():
    s = BrowserSettings(llm_providers=["anthropic", "gemini"], anthropic_api_key="k", gemini_api_key="g")
    assert [p.provider for p in build_llm(s).providers] == ["anthropic", "gemini"]
