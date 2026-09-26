"""Tool abstraction shared by MCP-backed and plain-Python tools, plus built-ins that need no MCP server.

Add your own Python tool:

    from browser_agent.tools import tool

    @tool("currency_convert", "Convert an amount between currencies",
          {"amount": {"type": "number"}, "from": {"type": "string"}, "to": {"type": "string"}})
    async def currency_convert(amount: float, **kw) -> str: ...

Or expose it from another package via the `alfred.browser_tools` entry-point group.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import Any

import httpx

log = logging.getLogger(__name__)

ToolFn = Callable[..., Awaitable[str]]

# Tool names containing these words only read state, so we skip the Jev risk check for them (saves latency).
READ_ONLY_HINTS = ("snapshot", "navigate", "search", "fetch", "screenshot", "tabs", "wait", "console",
                   "network", "find", "hover", "resize", "back", "list", "get", "read", "emulate", "open")


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    fn: ToolFn
    read_only: bool | None = None
    source: str = "builtin"

    def __post_init__(self) -> None:
        if self.read_only is None:
            lowered = self.name.lower()
            self.read_only = any(hint in lowered for hint in READ_ONLY_HINTS)

    def openai_schema(self) -> dict[str, Any]:
        params = {k: v for k, v in (self.parameters or {}).items() if k != "$schema"}
        params.setdefault("type", "object")
        params.setdefault("properties", {})
        return {"type": "function", "function": {"name": self.name, "description": self.description[:1000],
                                                 "parameters": params}}


_BUILTINS: dict[str, ToolSpec] = {}


def tool(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None,
         *, read_only: bool | None = None) -> Callable[[ToolFn], ToolFn]:
    def register(fn: ToolFn) -> ToolFn:
        _BUILTINS[name] = ToolSpec(name, description, {"type": "object", "properties": properties,
                                                       "required": required or []}, fn, read_only)
        return fn
    return register


def builtin_tools() -> list[ToolSpec]:
    specs = dict(_BUILTINS)
    for ep in entry_points(group="alfred.browser_tools"):
        try:
            obj = ep.load()
            for spec in obj if isinstance(obj, list | tuple) else [obj]:
                if isinstance(spec, ToolSpec):
                    specs[spec.name] = spec
        except Exception:
            log.exception("failed to load browser tool entry point %r", ep.name)
    return list(specs.values())


# --- built-ins ------------------------------------------------------------------------------------
@tool("web_search", "Search the web (DuckDuckGo). Returns titles, URLs and snippets. Use for quick lookups.",
      {"query": {"type": "string"}, "max_results": {"type": "integer", "description": "1-10, default 5"}},
      ["query"], read_only=True)
async def web_search(query: str, max_results: int = 5, **_: Any) -> str:
    from ddgs import DDGS

    def run() -> list[dict[str, Any]]:
        return list(DDGS().text(query, max_results=max(1, min(int(max_results or 5), 10))))

    results = await asyncio.to_thread(run)
    if not results:
        return "No results."
    return "\n\n".join(f"{i}. {r.get('title', '')}\n   {r.get('href', '')}\n   {r.get('body', '')}"
                       for i, r in enumerate(results, 1))


_SCRIPT_STYLE = re.compile(r"<(script|style|noscript|svg|head)[^>]*>.*?</\1>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\n\s*\n+")


def html_to_text(raw: str) -> str:
    text = _SCRIPT_STYLE.sub(" ", raw)
    text = re.sub(r"<(br|p|div|li|h[1-6]|tr)[^>]*>", "\n", text, flags=re.I)
    text = html.unescape(_TAG.sub(" ", text))
    text = re.sub(r"[ \t]+", " ", text)
    return _WS.sub("\n\n", text).strip()


@tool("fetch_url", "Fetch a web page over HTTP and return its readable text (no JavaScript). "
      "Faster than the browser for static pages and articles.",
      {"url": {"type": "string"}, "max_chars": {"type": "integer", "description": "default 6000"}},
      ["url"], read_only=True)
async def fetch_url(url: str, max_chars: int = 6000, **_: Any) -> str:
    async with httpx.AsyncClient(follow_redirects=True, timeout=20,
                                 headers={"User-Agent": "Mozilla/5.0 (Alfred OS browser agent)"}) as client:
        resp = await client.get(url)
    resp.raise_for_status()
    body = resp.text if "html" in resp.headers.get("content-type", "html") else resp.text
    text = html_to_text(body) if "<" in body[:1000] else body
    return f"URL: {resp.url}\n\n{text[: int(max_chars or 6000)]}"


# Control tools — handled by the agent loop itself, never executed as functions.
FINISH = "finish"
ASK_USER = "ask_user"


async def _control(**_: Any) -> str:  # pragma: no cover - intercepted by the loop
    return ""


CONTROL_TOOLS = [
    ToolSpec(FINISH, "Call when the task is complete. `answer` is the final, concise, spoken-friendly result "
             "(1-4 sentences, include the key facts you found).",
             {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]},
             _control, read_only=True, source="control"),
    ToolSpec(ASK_USER, "Ask the user a question when you cannot continue without their input "
             "(e.g. which account, missing details). The task pauses.",
             {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]},
             _control, read_only=True, source="control"),
]


@dataclass
class ToolResult:
    text: str
    is_error: bool = False
    meta: dict[str, Any] = field(default_factory=dict)
