"""OpenRouter chat client (OpenAI-compatible) with free-model rotation.

A free model that is rate-limited, down, or returns garbage is put on a short cooldown and the next
model in the list is tried, so a single flaky provider never stalls the agent.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


class LLMUnavailable(RuntimeError):
    pass


class DailyQuotaExceeded(LLMUnavailable):
    """OpenRouter free tier daily cap (50/day without credits, 1000/day with $10 credits). Retrying won't help."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str = ""
    parse_error: str | None = None


@dataclass
class ChatResult:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    model: str = ""
    latency_ms: int = 0

    def assistant_message(self) -> dict[str, Any]:
        msg: dict[str, Any] = {"role": "assistant", "content": self.content or ""}
        if self.tool_calls:
            msg["tool_calls"] = [
                {"id": c.id, "type": "function",
                 "function": {"name": c.name, "arguments": c.raw_arguments or json.dumps(c.arguments)}}
                for c in self.tool_calls
            ]
        return msg


class OpenRouterClient:
    def __init__(self, api_key: str, models: list[str], *, base_url: str = "https://openrouter.ai/api/v1",
                 timeout_s: float = 45.0, cooldown_s: float = 30.0, retry_rounds: int = 3,
                 backoff_s: float = 4.0, client: Any = None) -> None:
        if not models:
            raise ValueError("at least one model is required")
        if client is None:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(
                api_key=api_key, base_url=base_url, timeout=timeout_s, max_retries=0,
                default_headers={"HTTP-Referer": "https://github.com/sainitishmitta04/Alfred-OS", "X-Title": "Alfred OS"},
            )
        self.client, self.models = client, list(models)
        self.timeout_s, self.cooldown_s = timeout_s, cooldown_s
        self.retry_rounds, self.backoff_s = retry_rounds, backoff_s
        self._cooldown_until: dict[str, float] = {}

    def _candidates(self, preferred: str | None) -> list[str]:
        order = ([preferred] if preferred else []) + [m for m in self.models if m != preferred]
        now = time.monotonic()
        ready = [m for m in order if self._cooldown_until.get(m, 0) <= now]
        return ready or order  # all cooling down -> try anyway rather than fail

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
                   *, model: str | None = None, temperature: float = 0.2, max_tokens: int = 1200) -> ChatResult:
        """Try each model; if all fail (typically free-tier 429s), back off and do another round."""
        errors: list[str] = []
        for round_no in range(self.retry_rounds):
            if round_no:
                await asyncio.sleep(self.backoff_s * round_no)
                self._cooldown_until.clear()
            result = await self._round(messages, tools, model, temperature, max_tokens, errors)
            if result is not None:
                return result
        raise LLMUnavailable("all OpenRouter models failed: " + " | ".join(errors[-len(self.models):]))

    async def _round(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None, model: str | None,
                     temperature: float, max_tokens: int, errors: list[str]) -> ChatResult | None:
        for candidate in self._candidates(model):
            start = time.perf_counter()
            try:
                kwargs: dict[str, Any] = {"model": candidate, "messages": messages,
                                          "temperature": temperature, "max_tokens": max_tokens}
                if tools:
                    kwargs["tools"] = tools
                resp = await asyncio.wait_for(self.client.chat.completions.create(**kwargs), self.timeout_s)
                if not getattr(resp, "choices", None):
                    raise ValueError(f"empty response: {getattr(resp, 'error', None) or resp}")
                result = self._parse(resp, candidate)
                result.latency_ms = int((time.perf_counter() - start) * 1000)
                if not result.content and not result.tool_calls:
                    raise ValueError("model returned neither content nor tool calls")
                return result
            except Exception as exc:  # rotate on anything: 429, 5xx, 403, timeouts, malformed output
                if "free-models-per-day" in str(exc):
                    raise DailyQuotaExceeded("OpenRouter daily free-model quota is used up") from exc
                msg = f"{candidate}: {type(exc).__name__}: {str(exc)[:200]}"
                log.warning("OpenRouter call failed, rotating model — %s", msg)
                errors.append(msg)
                self._cooldown_until[candidate] = time.monotonic() + self.cooldown_s
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
            calls.append(ToolCall(id=tc.id or f"call_{i}", name=tc.function.name, arguments=args if isinstance(args, dict) else {},
                                  raw_arguments=raw, parse_error=error))
        return ChatResult(content=(message.content or "").strip(), tool_calls=calls, model=getattr(resp, "model", model) or model)

    async def validate_models(self) -> list[str]:
        """Drop configured models that are no longer free or no longer support tools. Best-effort."""
        try:
            listing = await asyncio.wait_for(self.client.models.list(), 15)
            info = {m.id: m for m in listing.data}
        except Exception as exc:
            log.warning("could not validate OpenRouter models: %s", exc)
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
