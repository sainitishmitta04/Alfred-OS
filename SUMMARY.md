# Alfred OS — Orchestration Engine + Browser Agent: Summary

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
tests/           52 pytest tests (no network except a local stdio MCP server)
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
- `pytest`: 52/52 pass (27 at the time of the first commit). Covers routing policy, confirmation approve/decline/double-confirm, timeout, agent/router
  exceptions, hooks, plugin overrides, the API, and SSE events.
- Live against the real Jev API. All 6 sample commands were routed correctly (direct/browser/knowledge/desktop),
  Jev latency was about 130–200ms, "delete everything in my downloads folder" was flagged destructive and paused
  for confirmation, and the SSE stream emitted live events.
- The Jev verifier gives mock responses low scores, which is expected until real agents are plugged in.

## Browser Agent (`browser_agent/`)
The real `browser` agent. It replaces the mock through `AGENT_OVERRIDES=browser=browser_agent:BrowserAgent`, and the engine core didn't need to change.

```
goal ─► Jev Noul "multi-step?" ─► (yes) Planner LLM splits into ≤4 sub-tasks (same-site flows stay together)
     ─► per sub-task tool loop (OpenRouter free model picks tools):
          tools = built-ins (web_search via DuckDuckGo, fetch_url) + every MCP server in mcp_servers.json
                  (Playwright MCP: 25 browser tools) + finish / ask_user
          every non-read-only call ─► Jev Noul "irreversible?" on the resolved element + keyword floor
                                     ─► ConfirmationRequired ─► engine pauses ─► /confirm ─► resume
          after each step          ─► Jev review: step_ok (Noul) + progress Choice{continue,done,stuck}
                                     confident verdicts become hints ("call finish" / "change approach")
     ─► earlier sub-task results feed later ones ─► synthesize one spoken answer
```

| Piece | File | Notes |
|---|---|---|
| Agent loop | `browser_agent/agent.py` | Step and time budgets, pause/resume state, history compaction, one shared browser (locked) |
| LLM | `browser_agent/llm.py` | OpenRouter via `openai` SDK. Rotates through free tool-capable models with cooldowns and backoff rounds, and fails fast on the daily quota |
| MCP | `browser_agent/mcp_pool.py`, `mcp_servers.json` | Any stdio or streamable-http MCP server. Each runs in its own task, tools are namespaced `server__tool`, a crashed server restarts on next use |
| Jev | `browser_agent/decisions.py` | `is_multi_step`, `risky`, `review_step` |
| Planner | `browser_agent/planner.py` | Plan and synthesize, with a keyword fallback if Jev is down |
| Tools | `browser_agent/tools.py` | `@tool` decorator, `alfred.browser_tools` entry points, deny-list for unsafe Playwright tools |

Engine addition: `ConfirmationRequired(prompt, state)` plus `Agent.resume()` / `Agent.cancel()`, so **any** agent can pause
partway through a task for approval. Covered by `tests/test_engine_pause.py`.

**Live-verified (real OpenRouter + Jev + Playwright):**
- "latest stable Python release" → web_search, then fetch_url → "3.14.7" in 21s.
- "HN top story + summarize" → navigated HN and summarized the story.
- httpbin order form → typed the name, then paused before "Submit order" (Jev 0.71 plus the keyword check).
- Wired into the server: Jev routes to `browser` at confidence 1.00.

**Known limits:**
- The OpenRouter free tier allows **50 requests/day without credits** (1000/day after a one-time $10 credit purchase). Testing hit this cap, and the agent now answers "quota used up" instead of hanging.
- Free models get 429s upstream often; rotation and backoff handle the transient ones.

**Server setup that was needed (Linux):** Playwright browser (`npx @playwright/mcp install-browser chrome-for-testing`),
plus Chromium system libraries and fonts through zypper. With no fonts installed, Chromium crashes on text-heavy pages. On macOS none of this is needed.

## Next steps
- Add OpenRouter credits (or a paid model in `OPENROUTER_MODELS`) for demo-day reliability.
- Optional: a Brave Search MCP (`BRAVE_API_KEY`) and a logged-in browser profile (drop `--isolated`, add `--user-data-dir`) for LinkedIn flows.
- Teammates register their Desktop and Knowledge agents.
- Optional: add a Haiku goal-cleanup step as a `before_dispatch` hook.
