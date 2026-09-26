"""LLM providers for the browser agent: Gemini (free tier) and OpenRouter (free models), both via the
OpenAI-compatible chat API, plus `LLMRouter` which tries providers in order.

Inside a provider, a model that is rate-limited, down, or returns garbage is put on a cooldown and the
next model is tried. If a whole provider is exhausted (e.g. daily quota), the router moves to the next.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


class LLMUnavailable(RuntimeError):
    pass


class DailyQuotaExceeded(LLMUnavailable):
    """A provider's daily free quota is exhausted (e.g. OpenRouter: 50/day without credits). Retrying won't help."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str = ""
    parse_error: str | None = None
    # Provider-specific fields that must be echoed back verbatim (e.g. Gemini 3 `extra_content.google.thought_signature`).
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatResult:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    model: str = ""
    latency_ms: int = 0
    # Anthropic only: the reply's content blocks as returned (thinking blocks included), sent back unchanged.
    anthropic_content: list[dict[str, Any]] | None = None

    def assistant_message(self) -> dict[str, Any]:
        msg: dict[str, Any] = {"role": "assistant", "content": self.content or ""}
        if self.tool_calls:
            msg["tool_calls"] = [
                {**c.extra, "id": c.id, "type": "function",
                 "function": {"name": c.name, "arguments": c.raw_arguments or json.dumps(c.arguments)}}
                for c in self.tool_calls
            ]
        if self.anthropic_content:
            msg["_anthropic_content"] = self.anthropic_content  # "_" keys are stripped for other providers
        return msg


class OpenAICompatClient:
    """One provider speaking the OpenAI chat-completions protocol, rotating across its models."""

    provider = "openai-compatible"
    # Substrings meaning "this whole provider is out for the day" -> raise DailyQuotaExceeded immediately.
    provider_quota_markers: tuple[str, ...] = ()
    # Substrings meaning "this model is out for the day" -> long cooldown for that model only.
    model_quota_markers: tuple[str, ...] = ()
    model_quota_cooldown_s = 3600.0
    default_headers: dict[str, str] = {}
    extra_create_kwargs: dict[str, Any] = {}

    def __init__(self, api_key: str, models: list[str], *, base_url: str,
                 timeout_s: float = 45.0, cooldown_s: float = 30.0, retry_rounds: int = 3,
                 backoff_s: float = 4.0, client: Any = None) -> None:
        if not models:
            raise ValueError("at least one model is required")
        if client is None:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout_s, max_retries=0,
                                 default_headers=self.default_headers or None)
        self.client, self.models = client, list(models)
        self.timeout_s, self.cooldown_s = timeout_s, cooldown_s
        self.retry_rounds, self.backoff_s = retry_rounds, backoff_s
        self._cooldown_until: dict[str, float] = {}

    def _daily_blocked(self, model: str) -> bool:
        return self._cooldown_until.get(model, 0) - time.monotonic() > self.cooldown_s

    def _candidates(self, preferred: str | None) -> list[str]:
        order = [m for m in ([preferred] if preferred else []) + [m for m in self.models if m != preferred]
                 if m in self.models or m == preferred]
        now = time.monotonic()
        ready = [m for m in order if self._cooldown_until.get(m, 0) <= now]
        # all briefly cooling down -> try anyway rather than fail; never retry models out of daily quota
        return ready or [m for m in order if not self._daily_blocked(m)]

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
                   *, model: str | None = None, temperature: float = 0.2, max_tokens: int = 1200) -> ChatResult:
        """Try each model; if all fail (typically free-tier 429s), back off and do another round."""
        errors: list[str] = []
        for round_no in range(self.retry_rounds):
            if round_no:
                await asyncio.sleep(self.backoff_s * round_no)
                self._cooldown_until = {m: t for m, t in self._cooldown_until.items() if self._daily_blocked(m)}
            if not self._candidates(model):
                raise DailyQuotaExceeded(f"{self.provider} daily free quota is used up for every model")
            result = await self._round(messages, tools, model, temperature, max_tokens, errors)
            if result is not None:
                return result
        raise LLMUnavailable(f"all {self.provider} models failed: " + " | ".join(errors[-len(self.models):]))

    async def _round(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None, model: str | None,
                     temperature: float, max_tokens: int, errors: list[str]) -> ChatResult | None:
        for candidate in self._candidates(model):
            start = time.perf_counter()
            try:
                kwargs: dict[str, Any] = {"model": candidate, "messages": [_public(m) for m in messages],
                                          "temperature": temperature, "max_tokens": max_tokens}
                if tools:
                    kwargs["tools"] = tools
                kwargs.update(self.extra_create_kwargs)
                resp = await asyncio.wait_for(self.client.chat.completions.create(**kwargs), self.timeout_s)
                if not getattr(resp, "choices", None):
                    raise ValueError(f"empty response: {getattr(resp, 'error', None) or resp}")
                result = self._parse(resp, candidate)
                result.latency_ms = int((time.perf_counter() - start) * 1000)
                if not result.content and not result.tool_calls:
                    raise ValueError("model returned neither content nor tool calls")
                return result
            except Exception as exc:  # rotate on anything: 429, 5xx, 403, timeouts, malformed output
                text = str(exc)
                if any(m in text for m in self.provider_quota_markers):
                    raise DailyQuotaExceeded(f"{self.provider} daily free quota is used up") from exc
                daily = any(m in text for m in self.model_quota_markers)
                msg = f"{candidate}: {type(exc).__name__}: {text[:200]}"
                log.warning("%s call failed, rotating model — %s", self.provider, msg)
                errors.append(msg)
                self._cooldown_until[candidate] = time.monotonic() + (self.model_quota_cooldown_s if daily else self.cooldown_s)
        if self.model_quota_markers and all(self._daily_blocked(m) for m in self.models):
            raise DailyQuotaExceeded(f"{self.provider} daily free quota is used up for every model")
        return None

    @staticmethod
    def _parse(resp: Any, model: str) -> ChatResult:
        message = resp.choices[0].message
        calls: list[ToolCall] = []
        for i, tc in enumerate(getattr(message, "tool_calls", None) or []):
            raw = tc.function.arguments or "{}"
            try:
                args = json.loads(raw) if raw.strip() else {}
                error = None if isinstance(args, dict) else "arguments must be a JSON object"
            except json.JSONDecodeError as exc:
                args, error = {}, f"invalid JSON arguments: {exc}"
            extra = dict(getattr(tc, "model_extra", None) or {})
            calls.append(ToolCall(id=tc.id or f"call_{i}", name=tc.function.name, arguments=args if isinstance(args, dict) else {},
                                  raw_arguments=raw, parse_error=error, extra=extra))
        return ChatResult(content=(message.content or "").strip(), tool_calls=calls, model=getattr(resp, "model", model) or model)

    async def validate_models(self) -> list[str]:
        return self.models


class OpenRouterClient(OpenAICompatClient):
    provider = "openrouter"
    provider_quota_markers = ("free-models-per-day",)
    default_headers = {"HTTP-Referer": "https://github.com/sainitishmitta04/Alfred-OS", "X-Title": "Alfred OS"}

    def __init__(self, api_key: str, models: list[str], *, base_url: str = "https://openrouter.ai/api/v1", **kw: Any) -> None:
        super().__init__(api_key, models, base_url=base_url, **kw)

    async def validate_models(self) -> list[str]:
        """Drop configured models that are no longer free or no longer support tools. Best-effort."""
        try:
            listing = await asyncio.wait_for(self.client.models.list(), 15)
            info = {m.id: m for m in listing.data}
        except Exception as exc:
            log.warning("could not validate %s models: %s", self.provider, exc)
            return self.models
        keep = []
        for name in self.models:
            meta = info.get(name)
            params = (getattr(meta, "supported_parameters", None) or (meta.model_extra or {}).get("supported_parameters", [])) if meta else []
            if meta and "tools" in params:
                keep.append(name)
            else:
                log.warning("dropping OpenRouter model %s (missing or no tool support)", name)
        if keep:
            self.models = keep
        return self.models


GEMINI_FALLBACK_MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite"]
_GEMINI_EXCLUDE = ("image", "tts", "audio", "live", "embedding", "vision", "thinking-exp", "learnlm", "aqa")


def _gemini_rank(model_id: str) -> tuple:
    """Newest version first; within a version prefer flash over flash-lite; stable before preview."""
    match = re.search(r"gemini-(\d+)(?:\.(\d+))?", model_id)
    version = (int(match.group(1)), int(match.group(2) or 0)) if match else (0, 0)
    return (version, "lite" not in model_id, "preview" not in model_id and "exp" not in model_id)


class GeminiClient(OpenAICompatClient):
    """Google Gemini via its OpenAI-compatible endpoint. Free tier limits are per model per day/minute."""

    provider = "gemini"
    model_quota_markers = ("PerDay", "per day", "RequestsPerDay")

    def __init__(self, api_key: str, models: list[str] | None = None, *,
                 base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/",
                 reasoning_effort: str | None = "low", **kw: Any) -> None:
        self._auto = not models
        # Browser steps are simple decisions; low thinking keeps each step fast. "" disables the override.
        self.extra_create_kwargs = {"reasoning_effort": reasoning_effort} if reasoning_effort else {}
        super().__init__(api_key, models or list(GEMINI_FALLBACK_MODELS), base_url=base_url, **kw)

    async def validate_models(self) -> list[str]:
        """If GEMINI_MODELS is unset, auto-pick the newest Flash models the key can use."""
        try:
            listing = await asyncio.wait_for(self.client.models.list(), 15)
            available = [m.id.removeprefix("models/") for m in listing.data]
        except Exception as exc:
            log.warning("could not list Gemini models: %s", exc)
            return self.models
        if self._auto:
            flash = [m for m in available if re.match(r"gemini-\d", m) and "flash" in m and not any(x in m for x in _GEMINI_EXCLUDE)]
            flash = [m for m in flash if not re.search(r"-\d{3}$|-\d{2}-\d{2}$", m)]  # skip pinned snapshots
            picked = sorted(set(flash), key=_gemini_rank, reverse=True)[:3]
            if picked:
                self.models = picked
        else:
            keep = [m for m in self.models if m in available]
            for m in set(self.models) - set(keep):
                log.warning("dropping Gemini model %s (not available for this key)", m)
            if keep:
                self.models = keep
        return self.models


def _public(message: dict[str, Any]) -> dict[str, Any]:
    """Drop provider-private keys (e.g. `_anthropic_content`) before a message goes to another provider."""
    return {k: v for k, v in message.items() if not k.startswith("_")}


def _to_anthropic(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """OpenAI-style history -> (system, Messages API turns). Consecutive same-role turns are merged, so a turn's
    tool results go back in one user message (tool results first, then any hint text)."""
    system: list[str] = []
    turns: list[dict[str, Any]] = []

    def add(role: str, blocks: list[dict[str, Any]]) -> None:
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"].extend(blocks)
        else:
            turns.append({"role": role, "content": list(blocks)})

    for m in messages:
        role = m.get("role")
        if role == "system":
            system.append(str(m.get("content") or ""))
        elif role == "assistant" and m.get("_anthropic_content"):
            add("assistant", m["_anthropic_content"])  # Claude's own reply, thinking blocks and all
        elif role == "assistant":  # produced by another provider earlier in this run
            blocks = [{"type": "text", "text": m["content"]}] if m.get("content") else []
            for call in m.get("tool_calls") or []:
                fn = call.get("function", {})
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                blocks.append({"type": "tool_use", "id": call["id"], "name": fn.get("name", ""),
                               "input": args if isinstance(args, dict) else {}})
            if blocks:
                add("assistant", blocks)
        elif role == "tool":
            add("user", [{"type": "tool_result", "tool_use_id": m["tool_call_id"],
                          "content": str(m.get("content") or "(empty result)")}])
        else:
            add("user", [{"type": "text", "text": str(m.get("content") or " ")}])
    return "\n\n".join(s for s in system if s), turns


class AnthropicClient:
    """Claude through the Anthropic SDK, with the same `chat()` contract as the OpenAI-compatible providers.

    The default model is Claude Opus 5 at low effort: each browser step is a small decision. Claude Opus 5.5 and
    Claude Fable 5.1 reject histories edited after the fact, and this agent shortens old tool results
    (`BrowserAgent._compact`), so don't point this at those models without turning that off.
    """

    provider = "anthropic"

    def __init__(self, api_key: str, models: list[str] | None = None, *, effort: str | None = "low",
                 timeout_s: float = 45.0, client: Any = None) -> None:
        if client is None:
            from anthropic import AsyncAnthropic

            client = AsyncAnthropic(api_key=api_key, timeout=timeout_s, max_retries=1)
        self.client, self.models = client, list(models or ["claude-opus-5"])
        self.effort, self.timeout_s = effort, timeout_s

    async def validate_models(self) -> list[str]:
        return self.models

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
                   *, model: str | None = None, temperature: float = 0.2, max_tokens: int = 1200) -> ChatResult:
        import anthropic

        name = model if model and model.startswith("claude") else self.models[0]  # planner names are OpenRouter's
        system, turns = _to_anthropic(messages)
        kwargs: dict[str, Any] = {"model": name, "messages": turns,
                                  # thinking shares this budget; the callers' limits are sized for answers only
                                  "max_tokens": max(max_tokens, 8000)}
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = [{"name": t["function"]["name"], "description": t["function"].get("description", ""),
                                "input_schema": t["function"].get("parameters") or {"type": "object", "properties": {}}}
                               for t in tools]
        if self.effort:
            kwargs["output_config"] = {"effort": self.effort}
        # No temperature: current Claude models reject sampling parameters.
        start = time.perf_counter()
        try:
            resp = await asyncio.wait_for(self.client.messages.create(**kwargs), self.timeout_s)
        except anthropic.BadRequestError as exc:
            if "credit balance" in str(exc):
                raise DailyQuotaExceeded(f"anthropic credit balance is too low: {exc}") from exc
            raise LLMUnavailable(f"anthropic rejected the request: {exc}") from exc
        except (anthropic.APIStatusError, anthropic.APIConnectionError, asyncio.TimeoutError) as exc:
            raise LLMUnavailable(f"anthropic {name}: {type(exc).__name__}: {str(exc)[:200]}") from exc
        if resp.stop_reason == "refusal":  # let the router try the next provider
            raise LLMUnavailable(f"anthropic {name} declined this request")

        calls = [ToolCall(id=b.id, name=b.name, arguments=dict(b.input or {}), raw_arguments=json.dumps(b.input or {}))
                 for b in resp.content if b.type == "tool_use"]
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        if not text and not calls:
            raise LLMUnavailable(f"anthropic {name} returned neither text nor tool calls")
        return ChatResult(content=text, tool_calls=calls, model=getattr(resp, "model", name) or name,
                          latency_ms=int((time.perf_counter() - start) * 1000),
                          anthropic_content=[b.model_dump(mode="json", exclude_none=True) for b in resp.content])


class LLMRouter:
    """Tries providers in order (e.g. Anthropic, then Gemini, then OpenRouter). Same interface as one provider."""

    def __init__(self, providers: list[Any]) -> None:
        if not providers:
            raise ValueError("no LLM provider configured — set ANTHROPIC_API_KEY, GEMINI_API_KEY or OPENROUTER_API_KEY")
        self.providers = providers

    @property
    def models(self) -> list[str]:
        return [f"{p.provider}:{m}" for p in self.providers for m in p.models]

    async def validate_models(self) -> list[str]:
        results = await asyncio.gather(*(p.validate_models() for p in self.providers), return_exceptions=True)
        for provider, result in zip(self.providers, results):
            if isinstance(result, Exception):
                log.warning("model validation failed for %s: %s", provider.provider, result)
        return self.models

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, **kw: Any) -> ChatResult:
        errors: list[str] = []
        all_quota = True
        for provider in self.providers:
            try:
                result = await provider.chat(messages, tools, **kw)
                result.model = f"{provider.provider}:{result.model}"
                return result
            except DailyQuotaExceeded as exc:
                errors.append(str(exc))
            except LLMUnavailable as exc:
                all_quota = False
                errors.append(str(exc)[:300])
            log.warning("provider %s unavailable, trying next", provider.provider)
        raise (DailyQuotaExceeded if all_quota else LLMUnavailable)(" || ".join(errors))


def build_llm(settings: Any) -> LLMRouter:
    """Construct the provider chain from BrowserSettings (order = settings.llm_providers)."""
    providers: list[Any] = []
    for name in settings.llm_providers:
        if name == "anthropic" and settings.anthropic_api_key:
            providers.append(AnthropicClient(settings.anthropic_api_key, settings.anthropic_models or None,
                                             effort=settings.anthropic_effort, timeout_s=settings.llm_timeout_s))
        elif name == "gemini" and settings.gemini_api_key:
            providers.append(GeminiClient(settings.gemini_api_key, settings.gemini_models or None,
                                          base_url=settings.gemini_base_url, timeout_s=settings.llm_timeout_s,
                                          reasoning_effort=settings.gemini_reasoning_effort))
        elif name == "openrouter" and settings.openrouter_api_key:
            providers.append(OpenRouterClient(settings.openrouter_api_key, settings.models,
                                              base_url=settings.openrouter_base_url, timeout_s=settings.llm_timeout_s))
        elif name not in {"anthropic", "gemini", "openrouter"}:
            log.warning("unknown LLM provider %r (expected anthropic/gemini/openrouter)", name)
    return LLMRouter(providers)
