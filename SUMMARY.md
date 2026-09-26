# Alfred OS — Orchestration Engine: Summary

## What it is
The central "brain" of Alfred. It takes a voice transcript, uses **Jev** (TypeSafe AI System One) to decide
which specialist agent handles it and whether it is destructive, asks for confirmation if needed,
dispatches to the agent, checks the result with Jev, logs every step to SQLite in real time, and
returns a structured, speakable response. It never crashes. Every failure path returns a friendly
fallback message and gets logged.

```
POST /transcript ─► before_route hooks
                   ─► Router: Jev (Choice + Noul, ~150ms)
                        │ confidence < 0.6 ─► Claude Haiku forced-choice fallback
                        │ Jev/Claude down  ─► offline keyword router
                   ─► destructive? ── yes ─► status=needs_confirmation ─► POST /confirm {approved}
                   ─► before_dispatch hooks ─► agent.run(goal, ctx)  (timeout, per-agent override)
                   ─► Jev verify: "was the goal satisfied?"  (logged step)
                   ─► after_dispatch hooks ─► SQLite + SSE event stream ─► JSON response
```

## Where Jev is used
| Decision | Jev primitive | Notes |
|---|---|---|
| Which agent? | `Choice` built from registered agents' descriptions | New agents are routable automatically |
| Destructive? | `Noul` with true/false criteria (threshold `DESTRUCTIVE_THRESHOLD`) | Asked in the **same call** as routing |
| Did the agent succeed? | `Noul` on `{user_goal, agent_response}` | Advisory `jev_verify` step for the UI. Turn off with `JEV_VERIFY=false` |

Claude is only called when Jev's confidence is below the threshold. When that happens, Jev's destructive verdict is still kept (the stricter of the two wins).
`route_source` records which path won: `jev`, `claude_fallback`, `jev_low_confidence` (no Claude available), or `keyword`.

## Layout
```
orchestrator/
  main.py        FastAPI app factory (create_app), lifespan starts/stops agents
  engine.py      Orchestrator: handle_transcript, confirm, hooks, timeouts, error handling
  router.py      JevClient, JevRouter, JevVerifier, ClaudeRouter, KeywordRouter, CompositeRouter
  db.py          sqlite3 schema from the spec + helpers (log_session, log_step, log_error, ...)
  events.py      in-process pub/sub feeding GET /events (SSE)
  config.py      .env loader (Settings)
  schemas.py     request/response models
  agents/
    base.py      Agent / AgentContext / AgentResult contract
    registry.py  discovery: built-ins → pip entry points (alfred.agents) → AGENT_OVERRIDES env
    adapters.py  wraps `async def run_x_agent(goal) -> str` into an Agent
    mocks.py     direct / browser / desktop / knowledge mocks (# MOCK — replace)
tests/           27 pytest tests (no network)
test_cli.py      end-to-end CLI with interactive confirmation
docs/EXTENDING.md  how teammates plug in their agents
```

## API
| Method | Path | Purpose |
|---|---|---|
| POST | `/transcript` `{transcript}` | Full flow. Returns `session_id, status, route, route_source, route_confidence, response_text, latency_ms, jev_latency_ms, agent_latency_ms, steps` |
| POST | `/confirm` `{session_id, approved}` | Second step for destructive actions (safe to call twice) |
| GET | `/sessions`, `/sessions/{id}`, `/sessions/{id}/steps` | History, action log, errors |
| GET | `/agents` | Registered agents and their routing descriptions |
| GET | `/events` | Live SSE stream (`session`, `step`, `status`, `error`) for the Electron action-log panel |
| GET | `/health` | Status, agents, whether Jev and the Claude fallback are enabled |

## For teammates: plugging in your agent (no core edits)
```bash
# .env
AGENT_OVERRIDES=desktop=desktop_agent.main:run_desktop_agent,knowledge=kb.agent:KnowledgeAgent
```
You can register a bare async function, an `Agent` subclass, or a pip entry point. Accept `ctx` and call
`ctx.step(action, detail)` to show live progress in the UI. Details are in `docs/EXTENDING.md`.

## Run
```bash
source .venv/bin/activate
uv sync
uvicorn orchestrator.main:app --port 8000
python test_cli.py "lower the volume"
python test_cli.py "delete the old screenshots on my desktop"   # prompts y/N
uv run pytest -q
```

## Config (`.env`, gitignored; template in `.env.example`)
`TYPESAFE_API_KEY`, `ANTHROPIC_API_KEY`, `DB_PATH`, `AGENT_TIMEOUT_S`, `JEV_TIMEOUT_S`,
`JEV_CONFIDENCE_THRESHOLD`, `DESTRUCTIVE_THRESHOLD`, `JEV_VERIFY`, `FALLBACK_MODEL`, `AGENT_MODEL`,
`AGENT_OVERRIDES`, `CORS_ORIGINS`.

## Verified
- `pytest`: 27/27 pass. Covers routing policy, confirmation approve/decline/double-confirm, timeout, agent/router
  exceptions, hooks, plugin overrides, the API, and SSE events.
- Live against the real Jev API. All 6 sample commands were routed correctly (direct/browser/knowledge/desktop),
  Jev latency was about 130–200ms, "delete everything in my downloads folder" was flagged destructive and paused
  for confirmation, and the SSE stream emitted live events.
- The Jev verifier gives mock responses low scores, which is expected until real agents are plugged in.

## Next steps
- Build the real Browser Agent (Playwright MCP + Brave MCP with a Jev per-step loop) and register it through `AGENT_OVERRIDES`.
- Teammates register their Desktop and Knowledge agents.
- Optional: add a Haiku goal-cleanup step as a `before_dispatch` hook.
