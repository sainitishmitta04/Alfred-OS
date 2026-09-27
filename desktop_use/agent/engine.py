from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

from desktop_use import config
from desktop_use.agent.prompts import ALFRED_SYSTEM_PROMPT
from desktop_use.tools.registry import TOOL_DEFINITIONS, TOOL_HANDLERS
from desktop_use.tools.system_utils import SystemUtilsError

ToolCallback = Callable[[str, dict[str, Any], dict[str, Any]], None]


class AgentEngine:
    """Anthropic Haiku tool-calling loop for background desktop chores."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        max_tool_rounds: int | None = None,
    ) -> None:
        self.api_key = api_key or config.ANTHROPIC_API_KEY
        self.model = model or config.ALFRED_AGENT_MODEL
        self.max_tool_rounds = max_tool_rounds or config.ALFRED_MAX_TOOL_ROUNDS

    async def run(
        self,
        user_message: str,
        on_tool: ToolCallback | None = None,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY is not set; add it to .env at the repo root")

        try:
            from anthropic import AsyncAnthropic
        except ImportError as error:
            raise RuntimeError("anthropic package is required. Run: uv pip install anthropic") from error

        client = AsyncAnthropic(api_key=self.api_key)
        messages: list[dict[str, Any]] = [{"role": "user", "content": user_message.strip()}]
        tool_results: list[dict[str, Any]] = []
        started = time.perf_counter()
        nudged = False

        for _ in range(self.max_tool_rounds):
            response = await client.messages.create(
                model=self.model,
                max_tokens=512,
                system=ALFRED_SYSTEM_PROMPT,
                tools=TOOL_DEFINITIONS,
                messages=messages,
            )

            assistant_blocks: list[dict[str, Any]] = []
            tool_uses: list[Any] = []
            final_text_parts: list[str] = []

            for block in response.content:
                if block.type == "text":
                    final_text_parts.append(block.text)
                    assistant_blocks.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    tool_uses.append(block)
                    assistant_blocks.append(
                        {
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        }
                    )

            messages.append({"role": "assistant", "content": assistant_blocks})

            if response.stop_reason != "tool_use" or not tool_uses:
                # The model sometimes narrates ("I'll open VS Code…") and stops without calling a tool, so
                # nothing runs. If it has done nothing at all yet, nudge it once to actually act.
                if not tool_results and not nudged:
                    nudged = True
                    messages.append({"role": "user", "content":
                        "You only described what you would do — nothing has happened yet. Do it now by calling the "
                        "tools. Do not reply with text until the actions are done."})
                    continue
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                return {
                    "summary": " ".join(final_text_parts).strip() or "Done.",
                    "tool_results": tool_results,
                    "latency_ms": elapsed_ms,
                }

            async def _invoke(tool_use: Any) -> dict[str, Any]:
                handler = TOOL_HANDLERS.get(tool_use.name)
                tool_input = dict(tool_use.input) if isinstance(tool_use.input, dict) else {}
                if handler is None:
                    payload = {"error": f"Unknown tool: {tool_use.name}"}
                else:
                    try:
                        payload = await handler(**tool_input)
                    except (SystemUtilsError, Exception) as error:  # noqa: BLE001
                        payload = {"error": str(error)}
                if on_tool is not None:
                    on_tool(tool_use.name, tool_input, payload)
                return {
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": json.dumps(payload),
                }

            parallel_results = await asyncio.gather(*(_invoke(item) for item in tool_uses))
            for item, result in zip(tool_uses, parallel_results, strict=True):
                tool_results.append({"tool": item.name, "input": item.input, "result": result["content"]})
            messages.append({"role": "user", "content": parallel_results})

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return {
            "summary": "Stopped after maximum tool rounds.",
            "tool_results": tool_results,
            "latency_ms": elapsed_ms,
        }
