from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parent
load_dotenv(REPO_ROOT / ".env")
load_dotenv(PACKAGE_ROOT / ".env")


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY")
ANTHROPIC_WORKSPACE_ID = env("ANTHROPIC_WORKSPACE_ID")
ALFRED_AGENT_MODEL = env("ALFRED_AGENT_MODEL", "claude-haiku-4-5-20251001")
ALFRED_MAX_TOOL_ROUNDS = int(env("ALFRED_MAX_TOOL_ROUNDS", "6"))
