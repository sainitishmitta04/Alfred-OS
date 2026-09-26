"""Starts every configured MCP server and exposes their tools as one flat, namespaced list.

Each server lives in its own background task that owns the transport's context managers
(anyio requires enter/exit in the same task). Tool calls from any task go through the shared
ClientSession. A crashed server is restarted once on the next call.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
from typing import Any

from browser_agent.config import MCPServerConfig
from browser_agent.tools import ToolResult, ToolSpec

log = logging.getLogger(__name__)

_SAFE = re.compile(r"[^a-zA-Z0-9_-]")


def tool_name(server: str, name: str) -> str:
    return _SAFE.sub("_", f"{server}__{name}")[:64]


def _attr(obj: Any, *names: str, default: Any = None) -> Any:
    """mcp 1.x uses camelCase fields, 2.x snake_case — accept both."""
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def result_to_text(result: Any) -> ToolResult:
    parts: list[str] = []
    for item in _attr(result, "content", default=[]) or []:
        kind = _attr(item, "type", default="")
        if kind == "text":
            parts.append(_attr(item, "text", default=""))
        elif kind == "image":
            parts.append("[image returned — not shown to the model]")
        elif kind in {"resource", "resource_link"}:
            resource = _attr(item, "resource", default=None)
            parts.append(_attr(resource, "text", default=None) or f"[resource {_attr(item, 'uri', default='')}]")
    structured = _attr(result, "structured_content", "structuredContent")
    if not parts and structured:
        parts.append(str(structured))
    return ToolResult("\n".join(p for p in parts if p) or "(no output)", bool(_attr(result, "is_error", "isError", default=False)))


class MCPServer:
    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self.session: Any = None
        self.tools: list[Any] = []
        self.error: str | None = None
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._ready = asyncio.Event()

    @property
    def alive(self) -> bool:
        return self.session is not None and self._task is not None and not self._task.done()

    async def start(self) -> None:
        self._stop, self._ready, self.error = asyncio.Event(), asyncio.Event(), None
        self._task = asyncio.create_task(self._serve(), name=f"mcp:{self.config.name}")
        try:
            await asyncio.wait_for(self._ready.wait(), self.config.startup_timeout_s)
        except asyncio.TimeoutError:
            self.error = f"startup timed out after {self.config.startup_timeout_s}s"
            await self.stop()
        if self.error:
            raise RuntimeError(f"MCP server {self.config.name!r} failed: {self.error}")

    async def _serve(self) -> None:
        from mcp import ClientSession

        try:
            async with contextlib.AsyncExitStack() as stack:
                if self.config.url:
                    from mcp.client.streamable_http import streamable_http_client

                    streams = await stack.enter_async_context(streamable_http_client(self.config.url))
                else:
                    from mcp import StdioServerParameters
                    from mcp.client.stdio import stdio_client

                    params = StdioServerParameters(command=self.config.command, args=self.config.args,
                                                   env={**os.environ, **self.config.env})
                    errlog = stack.enter_context(open(os.devnull, "w"))
                    streams = await stack.enter_async_context(stdio_client(params, errlog=errlog))
                session = await stack.enter_async_context(ClientSession(streams[0], streams[1]))
                await session.initialize()
                self.tools = list((await session.list_tools()).tools)
                self.session = session
                self._ready.set()
                await self._stop.wait()
        except BaseException as exc:  # noqa: BLE001 - report any startup/transport failure
            if not isinstance(exc, asyncio.CancelledError):
                self.error = f"{type(exc).__name__}: {exc}"
                log.warning("MCP server %s stopped: %s", self.config.name, self.error)
        finally:
            self.session = None
            self._ready.set()

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        if not self.alive:
            log.info("restarting MCP server %s", self.config.name)
            await self.start()
        result = await asyncio.wait_for(self.session.call_tool(name, arguments), self.config.call_timeout_s)
        return result_to_text(result)

    async def stop(self) -> None:
        self._stop.set()
        if self._task and not self._task.done():
            try:
                await asyncio.wait_for(asyncio.shield(self._task), 10)
            except (asyncio.TimeoutError, Exception):
                self._task.cancel()
                with contextlib.suppress(BaseException):
                    await self._task
        self.session = None


class MCPPool:
    def __init__(self, configs: list[MCPServerConfig]) -> None:
        self.servers = {c.name: MCPServer(c) for c in configs}
        self.status: dict[str, str] = {}

    async def start(self) -> None:
        async def boot(server: MCPServer) -> None:
            try:
                await server.start()
                self.status[server.config.name] = f"ok ({len(server.tools)} tools)"
            except Exception as exc:  # one bad server must not block the others
                self.status[server.config.name] = f"failed: {exc}"
                log.warning("%s", exc)

        await asyncio.gather(*(boot(s) for s in self.servers.values()))

    def tool_specs(self) -> list[ToolSpec]:
        specs: list[ToolSpec] = []
        for server in self.servers.values():
            for t in server.tools:
                remote = t.name

                async def call(_server: MCPServer = server, _remote: str = remote, **arguments: Any) -> ToolResult:
                    return await _server.call(_remote, arguments)

                specs.append(ToolSpec(
                    name=tool_name(server.config.name, remote),
                    description=_attr(t, "description", default="") or remote,
                    parameters=_attr(t, "input_schema", "inputSchema", default={}) or {},
                    fn=call,
                    source=f"mcp:{server.config.name}",
                ))
        return specs

    async def stop(self) -> None:
        await asyncio.gather(*(s.stop() for s in self.servers.values()), return_exceptions=True)
