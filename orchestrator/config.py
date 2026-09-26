"""Env-based configuration. Values come from the process env, with `.env` at the repo root as a fallback."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def _float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    return float(raw) if raw else default


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    return default if not raw else raw in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    typesafe_api_key: str = ""
    anthropic_api_key: str = ""
    db_path: str = "alfred.db"
    agent_timeout_s: float = 10.0
    jev_timeout_s: float = 5.0
    jev_confidence_threshold: float = 0.6
    destructive_threshold: float = 0.5
    jev_verify: bool = True
    jev_model: str | None = None
    fallback_model: str = "claude-haiku-4-5-20251001"
    agent_model: str = "claude-opus-5-5"
    # "name=module:attr,name2=module:attr" — swap a mock for a teammate's real agent without code changes.
    agent_overrides: dict[str, str] = field(default_factory=dict)
    cors_origins: list[str] = field(default_factory=lambda: ["*"])

    @classmethod
    def from_env(cls, env_file: str | Path | None = None) -> "Settings":
        load_dotenv(env_file or ROOT / ".env", override=False)
        overrides: dict[str, str] = {}
        for pair in os.getenv("AGENT_OVERRIDES", "").split(","):
            if "=" in pair:
                name, target = pair.split("=", 1)
                overrides[name.strip()] = target.strip()
        db_path = os.getenv("DB_PATH", "").strip() or "alfred.db"
        if db_path != ":memory:" and not Path(db_path).is_absolute():
            db_path = str(ROOT / db_path)
        return cls(
            typesafe_api_key=os.getenv("TYPESAFE_API_KEY", "").strip(),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
            db_path=db_path,
            agent_timeout_s=_float("AGENT_TIMEOUT_S", 10.0),
            jev_timeout_s=_float("JEV_TIMEOUT_S", 5.0),
            jev_confidence_threshold=_float("JEV_CONFIDENCE_THRESHOLD", 0.6),
            destructive_threshold=_float("DESTRUCTIVE_THRESHOLD", 0.5),
            jev_verify=_bool("JEV_VERIFY", True),
            jev_model=os.getenv("TYPESAFE_DEFAULT_MODEL", "").strip() or None,
            fallback_model=os.getenv("FALLBACK_MODEL", "").strip() or "claude-haiku-4-5-20251001",
            agent_model=os.getenv("AGENT_MODEL", "").strip() or "claude-opus-5-5",
            agent_overrides=overrides,
            cors_origins=[o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"],
        )


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()
