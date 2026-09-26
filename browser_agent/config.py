"""Browser agent settings (env) + MCP server config (`mcp_servers.json`)."""

from __future__ import annotations

import glob
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

# Free, tool-calling OpenRouter models, verified 2026-09-26. Order = preference; the client rotates on failure.
DEFAULT_MODELS = [
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "poolside/laguna-s-2.1:free",
    "qwen/qwen3.8-27b:free",
    "google/gemma-4-26b-a4b-it:free",
    "poolside/laguna-xs-2.1:free",
]


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, "").strip() or default


def _truthy(name: str, default: bool) -> bool:
    raw = _env(name).lower()
    return default if not raw else raw in {"1", "true", "yes", "on"}


def _find_playwright_browser() -> str:
    """Prefer the lightweight headless shell Playwright installs; empty = let Playwright MCP decide."""
    patterns = [
        "~/.cache/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell",
        "~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell",
    ]
    for pattern in patterns:
        hits = sorted(glob.glob(os.path.expanduser(pattern)))
        if hits:
            return hits[-1]
    return ""


@dataclass
class BrowserSettings:
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    models: list[str] = field(default_factory=lambda: list(DEFAULT_MODELS))
    planner_model: str | None = None
    llm_timeout_s: float = 45.0
    max_steps: int = 15
    timeout_s: float = 120.0
    headless: bool = True
    snapshot_chars: int = 6000
    typesafe_api_key: str = ""
    jev_confidence_threshold: float = 0.6
    risky_threshold: float = 0.5
    mcp_config_path: Path = ROOT / "mcp_servers.json"
    tool_denylist: set[str] = field(default_factory=set)

    @classmethod
    def from_env(cls) -> "BrowserSettings":
        load_dotenv(ROOT / ".env", override=False)
        headless = _truthy("BROWSER_HEADLESS", True)
        # Expose derived values so mcp_servers.json can reference them as ${VAR}.
        os.environ.setdefault("BROWSER_HEADLESS", "true" if headless else "false")
        if not _env("PLAYWRIGHT_EXECUTABLE") and headless and (exe := _find_playwright_browser()):
            os.environ["PLAYWRIGHT_EXECUTABLE"] = exe
        if not _env("BROWSER_NO_SANDBOX") and hasattr(os, "geteuid") and os.geteuid() == 0:
            os.environ["BROWSER_NO_SANDBOX"] = "true"  # Chromium refuses to sandbox as root
        os.environ.setdefault("ALFRED_TMP", str(Path(os.getenv("TMPDIR", "/tmp")) / "alfred"))
        models = [m.strip() for m in _env("OPENROUTER_MODELS").split(",") if m.strip()] or list(DEFAULT_MODELS)
        return cls(
            openrouter_api_key=_env("OPENROUTER_API_KEY"),
            openrouter_base_url=_env("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            models=models,
            planner_model=_env("OPENROUTER_PLANNER_MODEL") or None,
            llm_timeout_s=float(_env("OPENROUTER_TIMEOUT_S", "45")),
            max_steps=int(_env("BROWSER_MAX_STEPS", "15")),
            timeout_s=float(_env("BROWSER_TIMEOUT_S", "120")),
            headless=headless,
            snapshot_chars=int(_env("BROWSER_SNAPSHOT_CHARS", "6000")),
            typesafe_api_key=_env("TYPESAFE_API_KEY"),
            jev_confidence_threshold=float(_env("JEV_CONFIDENCE_THRESHOLD", "0.6")),
            risky_threshold=float(_env("BROWSER_RISKY_THRESHOLD", "0.5")),
            mcp_config_path=Path(_env("BROWSER_MCP_CONFIG", str(ROOT / "mcp_servers.json"))),
            tool_denylist={t.strip() for t in _env(
                "BROWSER_TOOL_DENYLIST",
                "playwright__browser_run_code_unsafe,playwright__browser_file_upload,playwright__browser_drag,playwright__browser_drop",
            ).split(",") if t.strip()},
        )


# --- MCP server config ----------------------------------------------------------------------------
@dataclass
class MCPServerConfig:
    name: str
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str | None = None           # streamable-http servers
    startup_timeout_s: float = 60.0
    call_timeout_s: float = 45.0


_VAR = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _expand(value: str) -> str:
    return _VAR.sub(lambda m: os.getenv(m.group(1), ""), value)


def _condition(expr: str) -> bool:
    """`VAR` -> VAR is set and non-empty; `VAR=value` -> equality (case-insensitive)."""
    name, _, expected = expr.partition("=")
    actual = os.getenv(name.strip(), "").strip()
    return actual.lower() == expected.strip().lower() if expected else bool(actual)


def load_mcp_servers(path: Path) -> list[MCPServerConfig]:
    """Parse mcp_servers.json. Supports `enabled`, `enabled_if_env`, `args_if_env`, and ${VAR} expansion."""
    if not path.exists():
        return []
    raw: dict[str, Any] = json.loads(path.read_text())
    servers: list[MCPServerConfig] = []
    for name, spec in raw.get("servers", {}).items():
        if not spec.get("enabled", True):
            continue
        if (cond := spec.get("enabled_if_env")) and not _condition(cond):
            continue
        args = [_expand(a) for a in spec.get("args", [])]
        for cond, extra in spec.get("args_if_env", {}).items():
            if _condition(cond):
                args += [_expand(a) for a in extra]
        servers.append(MCPServerConfig(
            name=name,
            command=spec.get("command"),
            args=args,
            env={k: _expand(v) for k, v in spec.get("env", {}).items()},
            url=_expand(spec["url"]) if spec.get("url") else None,
            startup_timeout_s=float(spec.get("startup_timeout_s", 60)),
            call_timeout_s=float(spec.get("call_timeout_s", 45)),
        ))
    return servers
