# Alfred-OS — background tasks + the desktop agent, end to end

Date: 2026-09-26 · Branch: `voice-input` · Status: plan for review, nothing implemented yet
Builds on [2026-09-26-voice-to-orchestrator.md](2026-09-26-voice-to-orchestrator.md) and `origin/main` at dc12f41 (browser agent PR #3, desktop-use PR #2).

## Goal

1. **Commands run in the background.** After you speak, the overlay says "On it" and gets out of the way. There's no waiting screen, even for a 125-second browser task. A **Tasks window** lists what's running and what finished, with live steps and each task's output. The overlay only comes back to tell you something finished, or when a task needs your yes or no.
2. **The desktop agent works end to end.** "Lower the volume" or "play music" goes voice → orchestrator → Jev → desktop agent → a real change on the Mac. It all starts with one command, so the demo runs and the result is on the way to shippable.

---

## 1. What's on `main` now

### How data flows (verified in the code)

```
UI ──POST /transcript {transcript}──► orchestrator ──Jev routes──► agent.run(goal, ctx)
                                                                    │
      ┌──── three ways an agent talks back ◄────────────────────────┘
      │ live:  ctx.step(action, detail, ok)          → SQLite agent_steps + SSE "step"
      │ pause: raise ConfirmationRequired(prompt, state)
      │        → status needs_confirmation, response_text = the agent's question;
      │          POST /confirm → agent.resume(state) or agent.cancel(state)
      │ done:  return AgentResult(text, success, data) → Jev checks it → completed | failed
      ▼
UI ◄── the HTTP response, only when the whole command is done + SSE /events (session, step, status, error)
```

- **What an agent receives:** only `goal`, which is the transcript, possibly rewritten by a hook, and `ctx` (session id, agent name, `step()`). It gets no history.
- **Same contract for every agent,** so the UI never needs anything agent-specific.
- **Never reaches the UI:** `AgentResult.data`.

### Browser agent

- **Connected** through `AGENT_OVERRIDES=browser=browser_agent:BrowserAgent`.
- **Live steps:** plenty (plan, subtask, think, each tool call, Jev risk check, Jev review, synthesize).
- **Pauses** before risky clicks, using `ConfirmationRequired` with its own question.
- **Limits:**
  - It can run up to 120 s (`BROWSER_TIMEOUT_S`).
  - One browser task at a time (it holds an internal lock).
  - The OpenRouter free tier allows 50 requests a day, and one browse uses several.
  - A clarifying question (`ask_user`) comes back as finished text instead of a pause. That gap is out of scope here.

### Desktop agent: not connected

- **What it is:** `desktop-use/backend` is Person C's standalone FastAPI service ("Alfred desktop-use backend", port 8787). It runs its own Anthropic Haiku tool loop.
- **Its tools:**
  - `control_media_player`: Spotify or Music play, pause, next, previous;
  - `execute_system_script`: battery, `set_volume`, `list_project_files`, and `run_osascript` (any AppleScript);
  - `headless_web_scrape`.
- **Its API:** `POST /api/v1/agent/execute {message}` returns `{summary, tool_results: [{tool, input, result}], latency_ms}`.
- **The orchestrator's `desktop` and `direct` routes still run mocks.** Nothing calls this service.
- **Its default model, `claude-3-5-haiku-20241022`,** is older than the orchestrator's `claude-haiku-4-5-20251001`.

### Why the current UI can't do background tasks

- **It waits for each answer, one command at a time.** Its client gives up after 30 s.
- **Session ids arrive too late.** The orchestrator only returns the `session_id` when the command is finished. A task list, live steps for several tasks, and answering a specific task's question all need that id as soon as the task starts.

---

## 2. Design

### 2.1 Orchestrator: background endpoints (small change to Person B's code)

```
POST /tasks {transcript}                 → 202 {session_id, status: "pending"}; the task runs in the background
POST /tasks/{session_id}/confirm {approved} → 202 {session_id}; the confirm or resume runs in the background
GET  /sessions?limit=50                  → exists: history for the Tasks window
GET  /sessions/{id}                      → exists: one task with its steps and errors
GET  /events                             → exists: live session, step, status and error events
```

- **Code changes:**
  - `engine.handle_transcript(transcript, session_id=None)` accepts an id supplied by the caller (one line).
  - `main.py` starts each run with `asyncio.create_task` and keeps the tasks in a set, so they aren't garbage-collected and are cancelled cleanly on shutdown.
  - `/transcript` and `/confirm` stay as they are, for `test_cli.py` and the existing tests.
- **Concurrency is already safe:** each command is its own session.
  - The browser agent's lock makes a second browser task wait inside `run`; the Tasks window shows its elapsed time.
  - Agent timeouts still apply to background runs.
- **Tests** in `tests/test_api.py`:
  - `/tasks` answers immediately with an id, and that id's events arrive;
  - the background task completes;
  - `/tasks/{id}/confirm` resumes a paused task, and declining cancels it.

### 2.2 Desktop agent adapter (new `desktop_agent/`, alongside `browser_agent/`)

```python
class DesktopAgent(Agent):                 # route "desktop"
    name, description = "desktop", "Mac control through AppleScript: open or quit apps, Finder actions, music playback, volume, battery, listing project files"
    timeout_s = 45                         # the service runs at most 6 Haiku rounds; the default AGENT_TIMEOUT_S is 10
    async def run(self, goal, ctx):
        ctx.step("desktop_request", goal)
        POST {DESKTOP_AGENT_URL}/api/v1/agent/execute {"message": goal}
        #   connection refused → AgentResult("The desktop agent isn't running.", success=False)
        #   503 (no Anthropic key) → AgentResult("The desktop agent isn't configured.", success=False)
        for r in tool_results: ctx.step(r["tool"], f"{input} → {result}", "error" not in result)
        return AgentResult(summary, data={"tool_results": ..., "latency_ms": ...})

class DirectAgent(DesktopAgent):           # route "direct": same service, the mock's routing description
    name, description = "direct", "<the mock's description, unchanged>"
```

- **Why two classes:** the registry keys an agent by its class's `name`, not by the `AGENT_OVERRIDES` key. `direct=desktop_agent:DesktopAgent` would only replace `desktop`, so "lower the volume", which Jev routes to `direct`, would still hit the mock.
- **Registration:** `AGENT_OVERRIDES=browser=browser_agent:BrowserAgent,desktop=desktop_agent:DesktopAgent,direct=desktop_agent:DirectAgent`.
- **Steps arrive when the service finishes,** not live: the service's API has no progress feed. That's fine for tasks that take seconds.
- **The service itself isn't edited.** It runs with `uv run --project desktop-use/backend uvicorn app.main:app --port 8787` (from `desktop-use/backend`).
  - Its config reads its own `.env`, but variables already in the environment win. So starting it with the root `.env` exported keeps **one `.env`** for everything.
  - Add `ALFRED_AGENT_MODEL=claude-haiku-4-5-20251001` there; the first real call confirms the model works.
- **Tests** (`tests/test_desktop_agent.py`, httpx mock transport):
  - the summary becomes the answer;
  - each tool result becomes a step;
  - the service being down, and a 503, give friendly failures.

### 2.3 UI: fire and forget, a Tasks window, and a confirmation queue

- **Main process** (`alfred.ts` in plan r4; `main.js` today):
  - **Task store:** a `Map` from session id to the task (transcript, status, route, steps, response, latencies, STT label and time).
    - It's filled from `GET /sessions?limit=50` at startup, so the history survives app restarts.
    - Then it's kept current from the live events.
  - **Live events:** one SSE connection (`fetch` stream plus a small parser, both pure and tested in `lib.js`) that reconnects with backoff. After a reconnect, running tasks are refreshed with `GET /sessions/{id}`.
  - **New command:** transcribe, `POST /tasks`, add the task to the store as pending, and show an "On it" toast on the overlay. There's no waiting, and commands no longer queue behind each other.
  - **Confirmations:** every task with status `needs_confirmation`, oldest first.
    - The overlay shows the oldest as a sticky card, with "2 more waiting".
    - The Yes/No buttons, or a take that's purely "yes" or "no", send `POST /tasks/{id}/confirm`.
    - **Any other take is a new task,** and the card stays. That's a change: today it asks again. With background tasks you should still be able to give new commands while a question waits.
- **Overlay:**
  - pill → "On it · {route}" toast for 2.5 s → collapses;
  - finished → a 6 s toast with the answer's first line, in alert style if the task failed; clicking it opens the Tasks window;
  - needs you → the sticky confirm card.
  - There's no "Thinking…" card any more.
- **Tasks window** (`tasks.html`): a normal, focusable 520×640 window in the same Batman palette. It opens from Tray ▸ Show tasks, or by clicking a toast. Newest first, one row per task:
  - a status mark: running (pulsing yellow), needs you (alert), done ✓, failed ✗, cancelled –;
  - the transcript, a route chip, elapsed time (ticking while running) and the latest step.
  - **Expanded row:** every step with a short label, the answer, latency chips (STT · Jev · agent · total) and Yes/No while pending.
  - **Empty state:** "No tasks yet — tap ⌥Space and ask Alfred something."

### 2.4 One command starts everything

- **At startup** the Electron app checks `/health` on the orchestrator (:8000) and the desktop service (:8787).
- **Any service that's down is started** with `uv run …`, passing the root `.env` values. Logs go to the app's data folder.
- **On quit** it stops only the services it started.
- **The tray** shows each service as online or offline.
- **Result:** `cd app && npm start` is the whole demo. It needs `uv` (already installed here). Bundling Python for real distribution comes later.

### End-to-end flow after this plan

```
⌥Space, speak, ⌥Space ─► main: STT (Deepgram India) ─► POST /tasks ─► 202 {session_id} ─► toast "On it"
orchestrator (background): Jev routes ─► desktop/direct → desktop_agent ─► HTTP ─► desktop service (Haiku + AppleScript)
                                        browser        → browser_agent (OpenRouter + Playwright MCP)
                            steps / pauses / result ─► SQLite + SSE
main: SSE ─► task store ─► Tasks window (live rows) + overlay (done toast, or the sticky Yes/No card)
Yes/No or a spoken yes/no ─► POST /tasks/{id}/confirm ─► agent.resume ─► more steps ─► done toast
```

---

## 3. Phases

| # | Phase | Done when |
|---|---|---|
| 1 | **Merge `origin/main` into `voice-input`** (two small conflicts: `.env.example` and `.gitignore`, where both sides appended lines) | All 52 orchestrator tests pass and `npm test` passes |
| 2 | **Desktop agent connected:** `desktop_agent/` with its tests; `.env` gets the overrides, `DESKTOP_AGENT_URL` and the model | See the list below |
| 3 | **Background API:** `/tasks`, `/tasks/{id}/confirm`, and the supplied-id change | The new API tests and the existing ones pass |
| 4 | **UI:** task store, SSE client, overlay toasts, confirmation queue, Tasks window | See the list below |
| 5 | **One-command start:** Electron starts the two backends | See the list below |

Phase 2, done when:
- With the desktop service and the orchestrator running, "lower the volume" sent to `/transcript` gets a real reply from the desktop agent, not the mock.
- The macOS volume changes: `osascript -e 'output volume of (get volume settings)'` shows the before and after values.

Phase 4, done when:
- The pure parts pass their tests: the SSE parser and the task-store updater.
- A preview take shows "On it" within about 1 s of the transcript.
- The Tasks window shows the task running with live steps, then done.
- A destructive command puts a sticky card up while another command runs in parallel.

Phase 5, done when:
- With nothing running, `npm start` brings up both backends and the tray shows them online.
- Quitting stops them.

Demo value by order: phase 2 makes the desktop real; phases 3 and 4 make everything asynchronous; phase 5 is polish, and until then the backends can be started by hand.

---

## 4. Keys needed in the root `.env`

| Key | For | Without it |
|---|---|---|
| `ANTHROPIC_API_KEY` | The desktop agent (required), and the orchestrator's Claude fallback | The desktop agent answers "not configured" |
| `TYPESAFE_API_KEY` | Jev routing, risk checks and verification | Routing falls back to keywords |
| `OPENROUTER_API_KEY` | The browser agent | The browser route fails at startup |
| `DEEPGRAM_API_KEY` | Speech-to-text | — (already set) |

---

## 5. Touches on teammates' code

- **Person B (orchestrator):** two new routes in `main.py`, one optional parameter in `engine.handle_transcript`, the new tests, and `desktop_agent/`. Nothing existing changes behaviour.
- **Person C (desktop service):** no edits; it's only started and called over HTTP.
  - **Safety note for them:** `run_osascript` runs AppleScript the model writes, and only the orchestrator's up-front destructive check guards it.
  - The HTTP API has no way to pause mid-task, unlike `ConfirmationRequired`.
  - For shippable, the service should return a "needs confirmation" answer before risky scripts.

## 6. Decisions — confirm or change

1. **Background tasks through the orchestrator's `/tasks` endpoints** (recommended). The alternative, a UI-only fire-and-forget with no orchestrator change, can't tell which live events belong to which of several running tasks.
2. **The `direct` route also goes to the desktop agent,** so "lower the volume" really does it.
3. **While a question waits,** a take that's purely yes or no answers it, and anything else becomes a new task.
4. **Electron starts the backends** (recommended), or a script does.
5. **The overlay shows a finished toast** for every task.

## 7. Risks

| Risk | Mitigation |
|---|---|
| A second browser task waits on the agent's lock without saying so | The row shows elapsed time; the agent could log "waiting for the browser" (Person B) |
| Paused tasks live in orchestrator memory, so a restart forgets them | Approving then re-runs the task from the start; the up-front check pauses it again |
| The older Haiku model id may be retired | Set `ALFRED_AGENT_MODEL` in the root `.env`; the phase 2 check confirms it |
| The OpenRouter free quota runs out during rehearsal | Add credits, or a paid model in `OPENROUTER_MODELS` (as their summary suggests) |
| Several windows need the same live data | One SSE connection and one store in the main process, sent to both windows over IPC |
