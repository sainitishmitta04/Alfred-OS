from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY")
ALFRED_AGENT_MODEL = env("ALFRED_AGENT_MODEL", "claude-3-5-haiku-20241022")
ALFRED_MAX_TOOL_ROUNDS = int(env("ALFRED_MAX_TOOL_ROUNDS", "6"))
