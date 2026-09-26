from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

from app import config
from app.agent.prompts import ALFRED_SYSTEM_PROMPT
from app.tools.desktop_control import control_media_player
from app.tools.system_utils import SystemUtilsError, execute_system_script
from app.tools.web_browser import headless_web_scrape

ToolHandler = Callable[..., Awaitable[dict[str, Any]]]

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "control_media_player",
        "description": "Control Spotify or Apple Music in the background (play, pause, next, previous).",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["play", "pause", "next", "previous", "toggle_play_pause"],
                },
                "track_or_playlist": {"type": "string", "description": "Optional search query."},
            },
            "required": ["action"],
        },
    },
    {
        "name": "headless_web_scrape",
        "description": "Headless browser read or interact with a web page without focus stealing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "action": {
                    "type": "string",
                    "enum": ["extract_text", "extract_html", "fill_input", "click"],
                },
                "selector": {"type": "string"},
                "input_value": {"type": "string"},
            },
            "required": ["url", "action"],
        },
    },
    {
        "name": "execute_system_script",
        "description": "Battery, volume, directory listing, or approved AppleScript utilities.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command_type": {
                    "type": "string",
                    "enum": ["battery_status", "set_volume", "list_project_files", "run_osascript"],
                },
                "args": {"type": "object", "additionalProperties": True},
            },
            "required": ["command_type"],
        },
    },
]

TOOL_HANDLERS: dict[str, ToolHandler] = {
    "control_media_player": control_media_player,
    "headless_web_scrape": headless_web_scrape,
    "execute_system_script": execute_system_script,
}


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

    async def run(self, user_message: str) -> dict[str, Any]:
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY is not set; add it to Alfred backend .env")

        try:
            from anthropic import AsyncAnthropic
        except ImportError as error:
            raise RuntimeError("anthropic package is required. Run: uv pip install anthropic") from error

        client = AsyncAnthropic(api_key=self.api_key)
        messages: list[dict[str, Any]] = [{"role": "user", "content": user_message.strip()}]
        tool_results: list[dict[str, Any]] = []
        started = time.perf_counter()

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
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                return {
                    "summary": " ".join(final_text_parts).strip() or "Done.",
                    "tool_results": tool_results,
                    "latency_ms": elapsed_ms,
                }

            async def _invoke(tool_use: Any) -> dict[str, Any]:
                handler = TOOL_HANDLERS.get(tool_use.name)
                if handler is None:
                    payload = {"error": f"Unknown tool: {tool_use.name}"}
                else:
                    try:
                        payload = await handler(**tool_use.input)
                    except (SystemUtilsError, Exception) as error:  # noqa: BLE001
                        payload = {"error": str(error)}
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
