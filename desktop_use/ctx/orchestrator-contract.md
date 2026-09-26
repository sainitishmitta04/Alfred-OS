# Desktop agent ↔ Orchestrator contract

This document defines what the **orchestration layer** must provide and what the **desktop agent** guarantees. Desktop ownership stops at this boundary; routing, Jev/TypeSafe, and confirmation flows are orchestrator-owned.

---

## Scope split

| Layer | Owner | Secrets / config |
|--------|--------|-------------------|
| Transcript → route `desktop` → confirm-if-destructive → dispatch | Orchestrator | `TYPESAFE_API_KEY` (optional), router fallbacks, `AGENT_TIMEOUT_S`, session DB |
| `goal` → Haiku tool loop → filesystem + native tools | Desktop agent | `ANTHROPIC_API_KEY`, `ALFRED_*`, `DESKTOP_FS_ALLOWED_DIRS` |

Desktop does **not** require `TYPESAFE_API_KEY`. Orchestrator does **not** implement desktop tools.

---

## Registration (orchestrator side)

The engine discovers the desktop agent at startup via built-in agents:

- **Module:** `orchestrator/agents/mocks.py`
- **Route name:** `desktop` (must match router output)
- **Handler:** `desktop_use.orchestrator_agent.run_desktop_agent`
- **Routing blurb:** `DESKTOP_AGENT_DESCRIPTION` (used in Jev/Claude/keyword routing)
- **Per-agent timeout:** `120` seconds (`FunctionAgent(..., timeout_s=120)`)

Overrides via `AGENT_OVERRIDES=desktop=...` are supported by the registry but **not required** for the default integration.

### Optional: direct desktop invoke (no routing)

For desktop development without TypeSafe/Jev:

- **`POST /agents/desktop/run`**
- **Body:** `{ "command": "<natural language goal>" }`
- **Response:** `{ "success", "summary", "steps", "data" }`

Same `run_desktop_agent` path as production dispatch; skips session DB and destructive confirmation unless you use `/transcript`.

---

## Dispatch contract (orchestrator → desktop)

When `route == "desktop"`, the orchestrator calls:

```python
await agent.run(goal, ctx)
```

### Inputs the orchestrator must pass

| Field | Source | Semantics |
|--------|--------|-----------|
| `goal` | `state["goal"]` | Command for the desktop agent. Initially equals `transcript`; hooks may rewrite in `before_dispatch`. |
| `ctx.transcript` | Original user transcript | Full utterance (for logging/context). Desktop should treat **`goal`** as the executable instruction. |
| `ctx.session_id` | Session UUID | Correlate steps in DB/UI. |
| `ctx.agent` | `"desktop"` | Fixed for this handler. |
| `ctx.settings` | Orchestrator `Settings` | Desktop reads **`settings.anthropic_api_key`** for Haiku. |
| `ctx.step(action, detail?, success?)` | Callback | Each tool/action should be logged for the live step stream. |

### Preconditions (orchestrator)

1. Routing has selected agent name **`desktop`**.
2. If the route was flagged **destructive**, orchestrator must **not** call `run` until the user **confirms** (`POST /confirm` with `approved: true`).
3. Dispatch is wrapped in `asyncio.wait_for(..., timeout=agent.timeout_s or AGENT_TIMEOUT_S)`.

### Outputs the orchestrator expects

| Return type | Required fields | Engine behavior |
|-------------|-----------------|-----------------|
| `AgentResult` | `text` (spoken/UI summary), `success` (default `True`) | Session `status`: `completed` if `success` else `failed`; `response_text = text` |
| `str` | — | Coerced to `AgentResult(text=str)` with `success=True` |

Optional `AgentResult.data` (desktop sets `tool_results`, `latency_ms`) is **not** required by the engine today but is safe to extend.

### Errors and timeouts

| Case | Desktop behavior | Orchestrator behavior |
|------|------------------|------------------------|
| Missing `ANTHROPIC_API_KEY` | `AgentResult(success=False, text=...)` after `ctx.step("error", ...)` | Session `failed` |
| Tool / runtime errors | Tool payload includes `"error"`; `success=False` if any tool result looks failed | Session `failed` |
| Exceeds timeout | — | Session `failed`, timeout message to user |
| Uncaught exception | — | `_fail`, logged to `errors` |

Post-dispatch **Jev verify** (`jev_verify`) is orchestrator-only; desktop is not involved.

---

## Desktop implementation map (this repo)

| Contract item | Implementation |
|---------------|----------------|
| Entrypoint | `desktop_use/orchestrator_agent.py` → `run_desktop_agent` |
| Tool loop | `desktop_use/agent/engine.py` (`AgentEngine.run`) |
| Tool registry | `desktop_use/tools/registry.py` |
| Filesystem tools | `desktop_use/tools/filesystem.py` (sandboxed; MCP-aligned names) |
| Native / fast tools | `desktop_control.py`, `system_utils.py`, `web_browser.py` |
| Standalone HTTP (optional) | `desktop_use/main.py` — same engine, not required for orchestrator |

### Environment (desktop)

Loaded from **repo root** `.env` (and optional `desktop_use/.env`):

```dotenv
ANTHROPIC_API_KEY=          # required for real runs
ALFRED_AGENT_MODEL=claude-3-5-haiku-20241022
ALFRED_MAX_TOOL_ROUNDS=6
DESKTOP_FS_ALLOWED_DIRS=    # optional; default Desktop, Documents, Downloads
```

---

## Routing hint (orchestrator / Jev)

Use this agent only when the user intent matches local desktop work (not general web browsing):

> Requires local file read/search/write/move/delete, listing folders, screenshots, media control, volume/battery checks, or app actions tied to local files — not general web browsing.

Exact string: `desktop_use.orchestrator_agent.DESKTOP_AGENT_DESCRIPTION`.

---

## Step log convention (desktop → UI)

Recommended `ctx.step` actions:

| Action | When |
|--------|------|
| `plan` | Start; `detail` = `goal` |
| `{tool_name}` | After each tool invocation; `detail` = tool input summary; `success` from tool outcome |
| `error` | Unrecoverable setup/runtime failure |

Orchestrator also logs engine steps: `route`, `dispatch`, `result`, `confirmation_*`, optional `jev_verify`.

---

## Testing without orchestrator secrets

| Test | Command / location |
|------|---------------------|
| Filesystem sandbox | `tests/test_desktop_filesystem.py` |
| Adapter wiring (mocked engine) | `tests/test_desktop_orchestrator_agent.py` |
| Full orchestrator suite | Uses **stub** desktop in `tests/conftest.py` (no Anthropic) |
| Manual desktop only | `POST /api/v1/agent/execute` on port 8787 or import `AgentEngine` |

---

## Implementation checklist (current branch)

- [x] `run_desktop_agent(goal, ctx)` registered as route `desktop`
- [x] Uses `ANTHROPIC_API_KEY` from orchestrator settings
- [x] Haiku tool loop with filesystem + native tools
- [x] Tool steps forwarded via `ctx.step`
- [x] Returns `AgentResult` with `success` + spoken `text`
- [x] 120s agent timeout registered
- [x] Direct test hook `POST /agents/desktop/run` (no TypeSafe)
- [ ] Orchestrator E2E with **live** Anthropic (manual; requires key)
- [ ] Production secret store (e.g. WixDBK) — **TBD**, out of desktop scope for local dev

---

## Version

- Contract version: **1.0**
- Alfred-OS desktop-use integration as of orchestrator `AgentContext` / `AgentResult` API.
