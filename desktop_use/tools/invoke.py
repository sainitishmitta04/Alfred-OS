from __future__ import annotations

import inspect
from typing import Any

from desktop_use.tools.registry import TOOL_HANDLERS


async def invoke_tool(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Call a registered tool by name (used by the direct invoke API and tests)."""
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        raise KeyError(f"Unknown tool: {name}")
    args = arguments or {}
    kwargs = {key: value for key, value in args.items() if value is not None}
    signature = inspect.signature(handler)
    filtered = {k: v for k, v in kwargs.items() if k in signature.parameters}
    return await handler(**filtered)
