"""SQLite persistence (stdlib sqlite3). Every routing decision and agent step is written as it happens."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  transcript TEXT NOT NULL,
  route TEXT,
  route_source TEXT,             -- 'jev' | 'claude_fallback' | 'jev_low_confidence' | 'keyword'
  route_confidence REAL,
  goal TEXT,
  is_destructive INTEGER DEFAULT 0,
  confirmed INTEGER,
  status TEXT DEFAULT 'pending', -- pending | routed | needs_confirmation | completed | failed | cancelled
  response_text TEXT,
  latency_ms INTEGER,
  jev_latency_ms INTEGER,
  agent_latency_ms INTEGER,
  created_at TEXT DEFAULT (datetime('now')),
  completed_at TEXT
);

CREATE TABLE IF NOT EXISTS agent_steps (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL REFERENCES sessions(id),
  agent TEXT NOT NULL,
  step_number INTEGER NOT NULL,
  action TEXT NOT NULL,
  detail TEXT,
  success INTEGER,
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS errors (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT REFERENCES sessions(id),
  message TEXT NOT NULL,
  stack TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_steps_session ON agent_steps(session_id, step_number);
"""

_SESSION_COLUMNS = {
    "transcript", "route", "route_source", "route_confidence", "goal", "is_destructive", "confirmed",
    "status", "response_text", "latency_ms", "jev_latency_ms", "agent_latency_ms", "completed_at",
}


def _bool_to_int(value: Any) -> Any:
    return int(value) if isinstance(value, bool) else value


class Database:
    """Thin thread-safe wrapper. Writes are tiny, so a single locked connection is plenty."""

    def __init__(self, path: str = "alfred.db") -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            if path != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(SCHEMA)

    def _exec(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # --- sessions ---------------------------------------------------------------------------------
    def log_session(self, session_id: str, transcript: str) -> None:
        self._exec("INSERT INTO sessions (id, transcript) VALUES (?, ?)", (session_id, transcript))

    def update_session(self, session_id: str, **fields: Any) -> None:
        unknown = set(fields) - _SESSION_COLUMNS
        if unknown:
            raise ValueError(f"unknown session columns: {sorted(unknown)}")
        if not fields:
            return
        assignments = ", ".join(f"{k} = :{k}" for k in fields)
        params = {k: _bool_to_int(v) for k, v in fields.items()} | {"_id": session_id}
        self._exec(f"UPDATE sessions SET {assignments} WHERE id = :_id", params)

    def update_session_status(self, session_id: str, status: str, **fields: Any) -> None:
        if status in {"completed", "failed", "cancelled"}:
            fields.setdefault("completed_at", self._now())
        self.update_session(session_id, status=status, **fields)

    def get_session(self, session_id: str, with_steps: bool = True) -> dict[str, Any] | None:
        row = self._exec("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            return None
        session = dict(row)
        if with_steps:
            session["steps"] = self.get_steps(session_id)
        return session

    def list_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._exec("SELECT * FROM sessions ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows.fetchall()]

    # --- steps & errors ---------------------------------------------------------------------------
    def log_step(
        self, session_id: str, agent: str, step_number: int, action: str,
        detail: str | None = None, success: bool | None = None,
    ) -> dict[str, Any]:
        cur = self._exec(
            "INSERT INTO agent_steps (session_id, agent, step_number, action, detail, success) VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, agent, step_number, action, detail, _bool_to_int(success)),
        )
        return dict(self._exec("SELECT * FROM agent_steps WHERE id = ?", (cur.lastrowid,)).fetchone())

    def next_step_number(self, session_id: str) -> int:
        row = self._exec("SELECT COALESCE(MAX(step_number), 0) FROM agent_steps WHERE session_id = ?", (session_id,)).fetchone()
        return int(row[0]) + 1

    def get_steps(self, session_id: str) -> list[dict[str, Any]]:
        rows = self._exec("SELECT * FROM agent_steps WHERE session_id = ? ORDER BY step_number, id", (session_id,))
        return [dict(r) for r in rows.fetchall()]

    def log_error(self, session_id: str | None, message: str, stack: str | None = None) -> None:
        self._exec("INSERT INTO errors (session_id, message, stack) VALUES (?, ?, ?)", (session_id, message, stack))

    def get_errors(self, session_id: str) -> list[dict[str, Any]]:
        rows = self._exec("SELECT * FROM errors WHERE session_id = ? ORDER BY id", (session_id,))
        return [dict(r) for r in rows.fetchall()]

    def _now(self) -> str:
        return self._exec("SELECT datetime('now')").fetchone()[0]
