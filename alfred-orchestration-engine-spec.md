# Alfred OS — Orchestration Engine Build Spec (v2: Python + Jev routing)
(Give this whole document to Claude Opus 5.5 as your build prompt)

## Context
I'm building "Alfred," a voice-controlled desktop AI agent for macOS. It's a hackathon project with a 3-person team. My job is the **Orchestration Engine** — the central brain that receives a text transcript (from a teammate's STT module) and routes it to the correct specialized agent, then returns a final response. Building this in **Python**, from scratch, as a standalone package that a separate Electron (or PyObjC/menu-bar) UI process will call into via IPC or a local HTTP/socket bridge.

## Key changes from v1
- **Routing decision now uses Jev (TypeSafe AI's System One model)**, not a Claude tool-use call. Jev takes unstructured state + a typed question and returns a typed decision (Choice/Score/Noul) with a calibrated confidence — no token-by-token generation, so it's much lower latency than a full Claude round-trip. This is exactly what top-level routing needs: a fast classification, not reasoning.
- **Orchestration engine itself is Python**, not Node. SQLite via the built-in `sqlite3` module (no extra dependency needed, unlike Node where we'd reach for `better-sqlite3`).
- Claude Opus 5.5 is still used, but only *inside* each specialized agent (Browser/Desktop/Knowledge) for actual reasoning — the orchestration engine's job is now purely: transcribe-in → Jev routes → dispatch → log → respond.

## What the orchestration engine must do
1. Receive a transcript string from the STT module (via HTTP POST to a local FastAPI endpoint — cleanest for a hackathon, gives a UI-callable REST interface for free)
2. Call Jev with a typed routing question to decide the path:
   - `direct` — trivial native command, dispatch straight to executor
   - `browser` — hand off to Browser Agent (async function `run_browser_agent(goal: str) -> str`, you-owned)
   - `desktop` — hand off to Desktop Agent (`run_desktop_agent(goal: str) -> str`, teammate-owned)
   - `knowledge` — hand off to Knowledge Agent (`run_knowledge_agent(goal: str) -> str`, teammate-owned)
3. Log every request/decision/response to SQLite (schema below)
4. Return a structured result: `{ route, response_text, latency_ms, steps: [...] }`
5. Handle errors/timeouts gracefully — never crash, always return a spoken-friendly fallback and log the failure

## Jev routing call — how to structure it
Use the official Python SDK (`pip install typesafe-sdk`). Ask two typed questions in one call against the transcript as state:

```python
from typesafe_sdk import TypeSafeClient, choice, noul

client = TypeSafeClient()  # reads TYPESAFE_API_KEY from env

result = client.system_one(
    state={"transcript": transcript},
    questions={
        "route": choice(
            "Which agent should handle this user request?",
            {
                "direct": "A single trivial native OS action with no ambiguity, e.g. volume, play/pause, opening a known app",
                "browser": "Requires live website interaction — search, social media, forms, looking things up online",
                "desktop": "Requires file read/search/write, or app-launching tied to file content",
                "knowledge": "Refers to notes, the Obsidian vault, or personal knowledge base",
            },
        ),
        "is_destructive": noul(
            "Could this action overwrite, delete data, or be otherwise irreversible?"
        ),
    },
)

route = result.answers["route"].choice
route_confidence = result.answers["route"].probabilities[route]
is_destructive = result.answers["is_destructive"].value
```

**Confidence threshold rule**: if `route_confidence < 0.6`, don't trust Jev's pick — fall back to a Claude call (small prompt, forced choice) to disambiguate. Log which path was used (`jev` vs `claude_fallback`) in the session row, since this is worth mentioning on stage as an example of thoughtful model routing, not just "we called an API."

**Goal restatement**: Jev returns a typed decision, not a clean natural-language goal string for the downstream agent. So after getting the route, do one lightweight step to produce the `goal` string the agent needs — either pass the raw transcript straight through (simplest, fine for most commands) or do a tiny Claude Haiku call to clean it up if the transcript is messy. Default to passing the raw transcript through; only add the cleanup step if you have time.

## Destructive-action confirmation flow
If `is_destructive` is true:
1. Return `{status: "needs_confirmation", proposed_action: transcript, route}` immediately, don't dispatch
2. Wait for a second call — `POST /confirm` with `{session_id, approved: bool}` — before dispatching
3. Log the confirmation prompt and decision to SQLite

## SQLite schema (Python `sqlite3`, stdlib — no extra install)
```sql
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  transcript TEXT NOT NULL,
  route TEXT,
  route_source TEXT,             -- 'jev' or 'claude_fallback'
  route_confidence REAL,
  goal TEXT,
  is_destructive INTEGER DEFAULT 0,
  confirmed INTEGER,
  status TEXT DEFAULT 'pending', -- pending | routed | needs_confirmation | completed | failed
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
```

Split `jev_latency_ms` and `agent_latency_ms` out separately — this is the exact number pair your demo's latency readout needs ("Jev routed in 90ms, agent responded in 850ms").

## Module structure to generate
```
/orchestrator
  ├── main.py           — FastAPI app: POST /transcript, POST /confirm, GET /sessions/{id}
  ├── router.py         — Jev call + confidence-threshold fallback to Claude
  ├── db.py             — sqlite3 setup, schema migration on first run, helper functions
  ├── agents.py         — dispatch layer calling into agent modules (mocked for now)
  ├── config.py         — env config loader (python-dotenv)
  └── requirements.txt
```

## Interfaces the engine depends on (mock these now, wire in real ones later)
```python
# agents.py — MOCK implementations, replace with real imports once ready
import asyncio

async def run_browser_agent(goal: str) -> str:
    await asyncio.sleep(0.5)
    return f"[MOCK] Browser agent would handle: {goal}"

async def run_desktop_agent(goal: str) -> str:
    await asyncio.sleep(0.3)
    return f"[MOCK] Desktop agent would handle: {goal}"

async def run_knowledge_agent(goal: str) -> str:
    await asyncio.sleep(0.3)
    return f"[MOCK] Knowledge agent would handle: {goal}"

async def run_direct_command(goal: str) -> str:
    await asyncio.sleep(0.1)
    return f"[MOCK] Direct command executed: {goal}"
```

## Non-functional requirements
- **Timeout**: every agent dispatch wrapped in `asyncio.wait_for(..., timeout=10)`, configurable via env; on timeout, log as failed, return a fallback message
- **Async throughout**: FastAPI + `async def` handlers, keep everything non-blocking so the UI stays responsive
- **CORS enabled** on the FastAPI app if the Electron UI calls it over `localhost` from a different port
- **Config via `.env`**: `TYPESAFE_API_KEY`, `ANTHROPIC_API_KEY`, `DB_PATH`, `AGENT_TIMEOUT_S`, `JEV_CONFIDENCE_THRESHOLD`

## What I need from you (Claude) right now
Generate the full `/orchestrator` Python package as described:
1. `db.py` — sqlite3 init + schema + all helper functions (`log_session`, `log_step`, `log_error`, `update_session_status`, `get_session`)
2. `router.py` — Jev typed-question call, confidence check, Claude fallback path
3. `agents.py` — dispatch layer with mock implementations, clearly marked `# MOCK — replace with real import`
4. `main.py` — FastAPI app wiring `/transcript` (full flow: route → confirm-if-destructive → dispatch → log → respond) and `/confirm` (second-step confirmation flow)
5. `config.py` — env-based config loader using `python-dotenv`
6. `requirements.txt` with all dependencies pinned to reasonable versions
7. A `test_cli.py` script I can run with `python test_cli.py "lower the volume"` to hit the local FastAPI server and print the full JSON response, so I can verify the flow end-to-end without any UI

Use Python 3.11+, type hints throughout, `httpx` if any internal HTTP calls are needed. Add clear comments marking every spot a teammate will plug in their real agent module later. Keep it dependency-light — this needs to run reliably on a laptop with no internet mid-demo except for the Jev/Claude API calls themselves.
