# Alfred-OS — voice input → orchestrator

Date: 2026-09-26 · Branch: `voice-input` (cut from `origin/main` at 8ac66e4) · Status: plan for review (revision 4), nothing implemented yet

- Revision 2: Echo is used as a reference, not a source (Appendix A).
- Revision 3: the speech-to-text provider and model are selectable.
- **Revision 4: connects to the orchestrator that landed on `main`.**
  - The orchestrator is a FastAPI service with Jev routing and its own SQLite log, so the hand-off is its `POST /transcript` API.
  - Speech-to-text moves into Electron's main process. The separate Python engine and our own `kb.sqlite` are dropped.
  - The UI gains what the team's demo needs: a live action log, a latency readout, and confirmation prompts.

## ⏱ Hackathon cut (one hour to submission) — build this first

Everything below this section is the full design, kept for after the demo. The cut trades robustness for fewer moving parts.

| Piece | Built in the hour | Deferred |
|---|---|---|
| App | Plain Electron (`app/`: `main.js`, `preload.js`, `index.html`), no bundler or TypeScript; menu-bar only, with a tray menu | Forge, Vite and TypeScript |
| Hotkey | Electron `globalShortcut`: tap ⌥Space to start, tap again to send; Esc is registered only while recording. No native module, no Accessibility permission | Hold-to-talk with uiohook |
| Capture | `getUserMedia` + `MediaRecorder` (webm/opus); an `AnalyserNode` drives the waveform from the recording stream | AudioWorklet, release tail, warm mic |
| Speech-to-text | Upload on release from the main process (keys stay there). Provider and model come from `.env` and can be switched in the tray: **Deepgram** `nova-3` (`mip_opt_out=true`) and **OpenAI** `gpt-4o-mini-transcribe`. A silent or empty take is dropped | Live streaming partials, Sarvam, fallback provider |
| Orchestrator | `POST /transcript` from the main process, one command at a time; the card shows route, response, latency chips (STT · Jev · agent · total) and steps from the response; `needs_confirmation` → [Yes] [No] buttons, or answer yes/no with the next take → `POST /confirm`; `/health` in the tray | SSE live steps, token header |

Demo check: with the orchestrator running, "lower the volume" completes with route and latency chips. "Delete the old screenshots on my desktop" asks first, then "yes" completes it and "no" cancels it. Switching the provider in the tray changes the STT chip.

### UI design (from the ui-ux-pro-max skill, with the Batman palette kept)

- **Skill output used:**
  - Style: Minimalism & Swiss — clean, high contrast, functional, clear type hierarchy.
  - Font: Inter, which the skill tags "dark, cinematic, technical … AI dashboards", with SF Pro as fallback.
  - Motion: transitions of 150–300 ms.
  - Checklist: SVG icons (no emoji), visible focus rings, pointer cursors, reduced-motion support, text contrast of at least 4.5:1, explicit confirmation before destructive actions, and loading → success or error feedback after every submit.
- **Overridden:** the skill's red and blue light palette and its "product demo" landing layout don't suit a dark overlay. The Batman palette stays:

```css
:root {
  --cave: #0B0D10;      /* surface at 94% opacity with 20 px backdrop blur */
  --armor: #16191E;     /* chips, secondary button */
  --gunmetal: #2A2F37;  /* 1 px hairlines, idle pill outline */
  --signal: #F5C518;    /* live waveform, active dot, primary button — used sparingly */
  --on-signal: #0B0D10; /* text on yellow */
  --ink: #ECEAE4;       /* response text */
  --muted: #8A9099;     /* heard text, steps, chips */
  --alert: #E0533D;     /* errors, destructive border */
}
```

- **Contrast on `--cave`:** ink about 16:1, signal about 12:1, muted about 6.5:1, alert about 5.1:1, all at least 4.5:1. They stay above 4.5:1 even with 6% of a white window showing through.
- **Layout:**
  - A fixed 460×300 transparent window, bottom-centre.
  - The card sits above the pill: at most 440 px wide, 16 px radius, 14/16 px padding.
  - The pill is fully rounded and 36 px tall when active; idle, it's a 44×8 capsule.
- **Type:** response 15 px; heard text and steps 13 px; chips 12 px; line height 1.45.
- **Motion:**
  - Enter in 180 ms ease-out, exit faster, in 120 ms.
  - Only transform and opacity are animated.
  - `prefers-reduced-motion` turns transitions off and freezes the bars.
- **Accessibility:**
  - The result region is `role="status" aria-live="polite"`.
  - Real `<button>`s, at least 36 px tall, labelled "Yes, do it" and "No".
  - A 2 px `--signal` focus ring.
- **States:**
  - Idle.
  - Listening: bars, plus "⌥Space to send · Esc to cancel".
  - Transcribing: a pulsing dot and the provider label.
  - Thinking: skeleton chips.
  - Result: heard text, response, route chip, latency chips, and up to 5 steps marked ✓ or ✗ with SVG icons.
  - Confirm: alert-coloured border, the orchestrator's question, [Yes, do it] in signal yellow, [No], and a hint to answer by voice.
  - Error: an alert hairline, the message and a fix, such as "Orchestrator offline — run `uvicorn orchestrator.main:app --port 8000`".

## Goal

Hold a hotkey anywhere on the Mac, speak, and release. The pill shows what Alfred hears, and the final text goes to the orchestrator. The pill then shows which agent took the command, the agent's steps as they happen, the answer, and the latencies. Destructive actions ask "yes or no?" first.

**This branch covers**
- The Electron app: menu-bar tray, plus a pill with an activity card.
- The hold-to-talk hotkey and microphone capture.
- Speech-to-text with a selectable provider and model.
- The client for the orchestrator's API: transcript, confirmation and live events.

**Not in this branch**
- Changes to the orchestrator (Person B's code). Requests for it are in §8.
- The agents, including the Knowledge Agent (Obsidian), which the vision doc also gives to Person A.
- Packaging, signing and Windows.

---

## 1. What's on `main`

`origin/main` (PR #1, "Add Alfred OS orchestration engine") is Person B's orchestrator, run with `uvicorn orchestrator.main:app --port 8000`.

| Endpoint | What it does | What the voice side does with it |
|---|---|---|
| `POST /transcript {transcript}` | Routes with Jev (falling back to Claude Haiku, then keywords), asks for confirmation if the action is destructive, runs the agent (10 s timeout), checks the result with Jev, logs every step, then answers. **It blocks until the command is done** | Sent once per final transcript, one at a time |
| `POST /confirm {session_id, approved}` | The second step for destructive actions. Safe to call twice; declining returns "Okay, I won't do that." | Sent after the user answers yes or no |
| `GET /events` (SSE) | Live `session`, `step`, `status` and `error` events, with a keepalive every 15 s | Drives the activity card while the request is running |
| `GET /health` | Status, agent names, and whether Jev and the Claude fallback are enabled | Tray status; checked at start and after failures |

The response carries `session_id`, `status` (completed, failed, needs_confirmation or cancelled), `route`, `route_source`, `route_confidence`, `is_destructive`, `proposed_action`, `response_text`, `latency_ms`, `jev_latency_ms`, `agent_latency_ms` and `steps`.

**Other facts that shape this plan**
- **SQLite is already covered.** Every session, step and error goes into `alfred.db` as it happens. Our transcripts land in `sessions.transcript` automatically, so revision 3's separate `kb.sqlite` is dropped. If a searchable memory is needed later, it belongs in that database.
- **Configuration is the repo-root `.env`,** loaded with python-dotenv. The voice side reads the same file.
- **The agents are mocks for now** (direct, browser, desktop, knowledge); teammates plug theirs in with `AGENT_OVERRIDES`.
  - The `desktop-use` branch holds Person C's desktop agent.
  - No branch has Electron or speech-to-text code yet.
- **Running the orchestrator needs `uv`,** which isn't installed on this machine: `brew install uv`, then `uv sync`.

**Problems found**
1. **The vision doc's speech-to-text choice doesn't work in Electron.** It lists the Web Speech API, but that API's speech recognition fails with a "network" error inside Electron, because it relies on a Google API key that only Chrome builds include (electron/electron#46143, still reported in 2025). The provider-based speech-to-text in this plan replaces it, and this branch updates the doc's line (P0).
2. **Any web page can drive the orchestrator.** It allows every origin (`CORS_ORIGINS=*`) and has no authentication. A page open in the user's browser could post a transcript, then approve its own destructive action through `/confirm`.
   - Setting `CORS_ORIGINS` to empty doesn't help, because the config falls back to `*`.
   - Our client calls from Electron's main process, which needs no CORS at all, so the fix costs the voice side nothing (§8).
3. **The request returns its `session_id` only at the end.** To show live steps, the client matches the SSE `session` event that arrives while its request is running. With one request at a time this is reliable; a client-supplied session id would make it exact (§8).
4. **A command can take a while:** up to about 5 s of routing, 10 s for the agent and 5 s of checking. The client allows 30 s and shows progress from the events in the meantime.

---

## 2. Design

```
┌───────────────────────────── Electron app (app/) ─────────────────────────────┐
│ page (renderer): pill + activity card                                          │
│   capture.worklet.ts ── 20 ms PCM16 frames ──┐   ▲ UI state                    │
│                                              ▼   │   (both over Electron IPC)  │
│ main process                                                                   │
│   hotkey.ts   uiohook-napi: hold Right ⌥, Esc, typing-chord detection          │
│   stt/        take pipeline + provider registry: Deepgram (streaming),         │
│               OpenAI and Sarvam (batch) ──► vendor APIs                        │
│   alfred.ts   orchestrator client: /transcript (one at a time), /confirm,      │
│               /events (SSE), /health                                           │
│   main.ts     tray, windows, permissions, .env                                 │
└──────────────────────────────────────┬─────────────────────────────────────────┘
                                       │ HTTP 127.0.0.1:8000
                                       ▼
                    orchestrator (Python, FastAPI), unchanged
                    Jev routing → agent → SQLite alfred.db → SSE
```

**Why speech-to-text lives in Electron's main process**
- **No new process and no new port.** Audio goes from the page to the main process over Electron IPC, not a local socket, so there's nothing for a web page to connect to and no token handshake.
- **No Python changes.** The orchestrator's HTTP API is the contract its spec already defines ("receives a text transcript from a teammate's STT module via HTTP POST"). The two slices don't edit each other's code.
- **Vendor keys stay in the main process;** the page never sees them.
- **What the voice side needs is built in:** Node's `fetch`, `WebSocket` and `FormData`, plus `process.loadEnvFile` for the shared `.env`. The only new dependency is `uiohook-napi`, alongside Electron's own toolchain.
- **The alternative,** if you'd rather keep speech-to-text in Python: a FastAPI router mounted on the orchestrator's app, handing off in-process through `engine.handle_transcript()`. It costs an edit to Person B's `main.py` and a token-protected local WebSocket (decision 1).

**One command, end to end**

```
hold ⌥ ─► pill: listening; mic opens; take 12 starts; the Deepgram connection opens
speak  ─► frames → main → Deepgram (backlog first); live partials → pill
release─► 200 ms release tail → Finalize → final text (≈150 ms); a silent take is dropped here
       ─► pill: "Heard: delete the old screenshots on my desktop", with an STT latency chip
       ─► POST /transcript (queued if another command is still running)
          SSE: session → status "routed" (route chip) → steps (activity card)
       ─► response:
          completed          → the answer + latency chips (STT · Jev · agent)
          failed             → the answer, in the alert style
          needs_confirmation → "Should I go ahead and …?"  [Yes] [No], or hold ⌥ and say yes / no
                               → POST /confirm → completed | cancelled
```

**Repository layout.** Everything new is under `app/`. Outside it, this branch only changes `.env.example`, `.gitignore` and one line of the vision doc.

```
app/                               Electron Forge, vite-typescript template
  src/main/main.ts                 tray, windows, permissions, .env, wiring
  src/main/hotkey.ts               uiohook-napi + the hold-to-talk state machine
  src/main/stt/index.ts            take pipeline, registry, silence check, fallback, long-take splitting
  src/main/stt/deepgram.ts         streaming + batch
  src/main/stt/openai.ts           batch (+ Whisper phrase filter)
  src/main/stt/sarvam.ts           batch
  src/main/alfred.ts               orchestrator client
  src/preload.ts                   IPC bridge: frames up, UI state down
  src/pill/index.html  pill.css  pill.ts  capture.worklet.ts
  test/                            vitest, with fake WebSocket and fetch; no network
```

---

## 3. Capture (page)

Same design as revision 3, with one change: frames go to the main process over IPC instead of a socket.

- **One 16 kHz audio context** for the app's lifetime; Chromium resamples the mic into it.
- **The AudioWorklet** posts 20 ms PCM16 frames along with their level. The level comes from the frames being sent, so the waveform can't show sound that isn't going anywhere.
- **Per take:**
  - open the mic on key-down;
  - on key-up, record a 200 ms release tail, flush the last frame, then stop the tracks so the mic indicator goes off;
  - Esc stops at once.
- **Device loss** (`devicechange`, or a track `ended`): send what was captured, and show "Microphone disconnected".
- **Warm-mic window** with a 300 ms pre-roll: off by default.

---

## 4. Speech-to-text (main process)

**Take lifecycle**

```
start  ─► Take(id, provider, model)          the selection is fixed for the take
          streaming provider → open its connection now; audio queues until it's open
frame  ─► buffer + send queue (backlog first); partials → pill
commit ─► silence check: level never above the noise floor → dropped as empty
       ─► streaming: Finalize → final text (timeout ≈1 s)  |  batch: transcribe(buffer)
          failure, timeout or vendor error → fallback provider: transcribe(buffer), one retry on 429/5xx
       ─► CloseStream ─► final text → orchestrator client
```

**Rules**
- A take shorter than 200 ms is dropped.
- At 60 s the take is sent automatically; audio is never trimmed.
- Results that arrive after a take's final text are ignored.
- A cancel names its take, so it can't affect another one.

**Provider registry** (as in revision 3, now in TypeScript)
- **Each provider declares:**
  - id, label, and the environment variable holding its key;
  - its menu models, the first being the default;
  - whether it streams;
  - how it applies custom vocabulary (`keyterm`, `prompt` or `none`);
  - its batch length limit (longer takes are split at the quietest point);
  - its default language.
- **Every provider** has `transcribe(pcm, opts) → text`. Streaming providers also have `openStream(opts, onPartial) → { send, finalize, close }`, with one send queue per connection.
- **Deepgram's streaming connection** uses Node's built-in `WebSocket`. That client can't set headers, so the key goes in the `token` subprotocol, which Deepgram accepts.

| Provider | Menu models | Mode | Vocabulary | Notes |
|---|---|---|---|---|
| Deepgram | nova-3 (default), nova-2 | streaming + batch | keyterms | `mip_opt_out=true`; `language` `en`, or `multi` for mixed-language speech |
| OpenAI | gpt-4o-mini-transcribe, gpt-4o-transcribe, whisper-1 | batch | transcription `prompt` | Whisper phrase filter ("Thanks for watching") |
| Sarvam | models from Sarvam's current docs | batch | none | Its realtime streaming API is a later adapter |

**Configuration** lives in the repo-root `.env`, read with `process.loadEnvFile`. These lines are appended to `.env.example`:

```
DEEPGRAM_API_KEY=
OPENAI_API_KEY=
SARVAM_API_KEY=
STT_PROVIDER=deepgram
STT_MODEL=nova-3
STT_LANGUAGE=en
STT_VOCABULARY=Alfred,Slack,Safari
STT_FALLBACK_PROVIDER=deepgram
STT_FALLBACK_MODEL=nova-3
ORCHESTRATOR_URL=http://127.0.0.1:8000
ALFRED_TOKEN=
```

- **Tray ▸ Speech recognition** switches provider and model for the running session, labelled "until restart". `.env` holds the defaults (decision 2).
- **Validation:**
  - An unknown provider is an error on the tray and the pill.
  - A provider without a key shows as "(no key)".
  - An unrecognised model id is accepted and logged as custom.
- **Timing log:** one JSON line per take in the app's data folder.
  - It records provider, model, mode, key-down → first frame, connect time, seconds of audio, release → final text, and the orchestrator's session id and latencies.
  - No transcript text; the orchestrator's database already has it.

---

## 5. Hotkey

Unchanged from revision 3:
- **Why not Electron's built-in shortcuts:** `globalShortcut` has no key-release event, so it can't do hold-to-talk.
- **What to use instead:** `uiohook-napi` gives real key-down and key-up events. On macOS it needs the Accessibility permission, and possibly Input Monitoring too.
- **Default hotkey:** hold Right ⌥. Fn later, through a small Swift helper.

```
idle ──⌥ down──► listening            show the pill and start capture at once
listening ──⌥ up──► finishing         the release tail runs, then commit
listening | finishing ──Esc──► idle   cancel
listening ──any other key──► idle     cancel: it was a typing chord like ⌥+e, not push-to-talk
repeated key-down while held: ignored
```

New in this revision: while a confirmation is waiting, the next take is the answer (§7).

---

## 6. UI: pill + activity card (Batman palette)

**The window**
- One transparent, fixed-size panel at the bottom centre of the display the cursor is on: the pill at the bottom, the activity card above it.
- It never takes focus (`type: 'panel'`, `focusable: false`, `showInactive()`).
- It floats over full-screen apps and shows on every desktop Space.
- Mouse clicks pass through it, except on the Yes/No buttons while a confirmation is showing: `setIgnoreMouseEvents(true, { forward: true })`, toggled when the pointer is over a button.

**Pill states**

| State | Shows |
|---|---|
| Idle | A 40×8 px dark capsule with a faint gunmetal outline |
| Listening | 14 yellow bars driven by the frames being sent, plus live text for streaming providers |
| Finishing | The bars settle into one pulsing yellow dot; batch providers also show "Transcribing…" |
| Heard | The final text, with an STT chip such as "Deepgram nova-3 · 170 ms" |
| Error | A red hairline with a short reason: "Microphone disconnected", "Orchestrator offline", "Unknown provider in .env", "Needs Accessibility" |

**Activity card** — appears when the transcript is sent, and fades 4 s after the result
- **Route chip:** agent · route source · confidence, e.g. "desktop · jev · 0.93".
- **Live steps** from the events: action and detail, marked ✓, ✗ or … while running.
- **Result:** `response_text` in ink, or in the alert colour if the command failed.
- **Latency chips:** "STT 170 ms" · "Jev 142 ms" · "agent 850 ms" · "total 1.3 s". The vision doc treats this readout as a demo feature, and speech-to-text is our part of that story.
- **Confirmation:** the orchestrator's question with [Yes] [No], and "or hold ⌥ and say yes / no". No answer within 20 s counts as No.
- **Queued:** "1 queued" when a new command is waiting for the current one.

**Tray menu**
- Orchestrator status: online or offline, plus the agent names from `/health`.
- The hotkey hint.
- Speech recognition ▸ provider / model.
- Open .env.
- Quit.

**Palette** (unchanged)

```css
:root {
  --cave:        #0B0D10;              /* pill and card body, 88% opacity */
  --armor:       #16191E;              /* raised surfaces: chips, buttons */
  --gunmetal:    #2A2F37;              /* outlines, idle bars */
  --signal:      #F5C518;              /* bat-signal yellow: waveform, active step, Yes button */
  --signal-glow: rgb(245 197 24 / 0.35);
  --ink:         #ECEAE4;              /* transcript and answer text */
  --muted:       #8A9099;              /* steps, chips, hints */
  --alert:       #E0533D;              /* errors, failed steps, No button hover */
}
```

- System font (SF Pro), 13 px.
- Always dark, whatever the system theme.
- Tray icon: a generic bat or a butler's bow tie, not DC's Batman logo.

---

## 7. Orchestrator client (`alfred.ts`)

- **One command at a time.** A new final transcript waits for the previous command to finish, including its confirmation (Echo lesson 7771f87), and the card shows "queued".
- **Confirmations.** While a command is `needs_confirmation`, the next take's text goes through `parseYesNo`:
  - "yes", "yeah", "yep", "sure", "go ahead", "do it" and "confirm" approve;
  - "no", "nope", "don't", "stop" and "cancel" decline;
  - anything else asks again.
  - The buttons and the 20 s timeout go through the same `answer(approved)` path, so a double answer can't send two `/confirm` calls (the orchestrator guards against that too).
- **Live events.** The main process holds one SSE connection (`fetch` plus a roughly 20-line parser) and reconnects if it drops.
  - Events whose `session_id` matches the running command drive the card.
  - If the event stream is down, the card fills from the final response's `steps` instead.
- **Timeouts and errors.**
  - `/transcript` gets 30 s.
  - If the connection is refused, the card shows "Orchestrator offline — start it with `uvicorn orchestrator.main:app --port 8000`" and keeps the transcript visible, so nothing is lost.
  - Any other failed response shows its status in the alert style.
- **Token.** Every request carries an `X-Alfred-Token` header when `ALFRED_TOKEN` is set.

---

## 8. Requests for the team

| For | Item | Why |
|---|---|---|
| Team | Replace "STT: Web Speech API" in `alfred-vision-and-architecture.md` §5 with provider-based speech-to-text. This branch does it in P0 | Web Speech recognition fails inside Electron |
| Person B | Check an `ALFRED_TOKEN` header on every route, and default CORS to no origins. Today `CORS_ORIGINS=` falls back to `*`; until that changes, set it to a dummy origin such as `app://alfred` | Any web page can currently post a transcript and approve its own destructive action. The voice client already sends the header and needs no CORS |
| Person B, nice-to-have | Let `/transcript` accept a client-supplied `session_id` | The live card could then follow its session without matching events |
| Person B, nice-to-have | A cancel endpoint for a running session | Esc could then stop a long agent run |
| Everyone | `uv` for the orchestrator; `npm` for `app/` | `uv` isn't installed on this machine |

---

## 9. Phases

The demo path comes first (P0–P3), then the provider selection (P4). P5 is optional polish.

| # | Phase | Done when |
|---|---|---|
| P0 | **Scaffold `app/`** (Forge vite-typescript); read the root `.env`; `/health` check; tray status; append the voice keys to `.env.example`; update the vision doc's speech-to-text line | `npm start` shows "Orchestrator: online · direct, browser, desktop, knowledge" while uvicorn runs, and "offline" when it doesn't |
| P1 | **Pill and card window,** palette, and every state (driven from a dev menu); uiohook hotkey and state machine; permission onboarding | Holding ⌥ shows the listening pill within 50 ms; ⌥+e is ignored; Esc cancels; state-machine tests pass |
| P2 | **Capture worklet, take pipeline, Deepgram streaming** with batch fallback | See the P2 list below |
| P3 | **Orchestrator client:** one-at-a-time queue, live card, confirmation (voice, buttons, timeout), latency chips, offline handling | See the P3 list below |
| P4 | **Provider selection:** registry, OpenAI and Sarvam batch adapters, vocabulary mapping, fallback provider, tray submenu | Switching in the tray changes the next take, and the STT chip shows it; an unknown provider shows an error; a missing key shows "(no key)"; adapter parsing tests pass |
| P5 | **Optional:** speak replies with the built-in macOS voice (`speechSynthesis`; pressing ⌥ stops it); warm-mic window; 60 s cap; device-loss message | Each item behaves as described in §3–§6 |

P2, done when:
- **Release tail:** "open Slack", released right on the "k", keeps "Slack".
- **First word:** the first word survives speaking the instant you press.
- **Latency:** the final text lands within 300 ms of release.
- **Fake-Deepgram tests pass:**
  - audio sent before the connection opens is kept;
  - `Finalize` leaves after the last frame;
  - the fallback runs when the connection never opens, drops, times out or returns an error;
  - late results are ignored;
  - a silent take is never sent.

P3, done when:
- **Simple command:** "lower the volume" completes, with route and latency chips.
- **Destructive command:** "delete the old screenshots on my desktop" asks the question. Saying "yes" completes it; saying "no" gives "Okay, I won't do that."
- **Ordering:** two quick commands run in order.
- **Offline:** with the orchestrator stopped, the pill says so and keeps the transcript.
- **Tests pass:** the yes/no parser, the queue, the SSE parser and session matching.

---

## 10. Risks

| Risk | How to check | If it bites |
|---|---|---|
| Opening the mic on key-press clips the first word | Key-down → first frame in the timing log | Enable the warm-mic window |
| A per-take Deepgram connection slows short takes | Connect time compared with take length | Pre-open the connection while the warm-mic window is on |
| Node's built-in `WebSocket` and Deepgram's token subprotocol don't work together | The first P2 run | The `ws` package, with an Authorization header |
| Event matching picks the wrong session when another client posts at the same moment (for example `test_cli.py`) | P3 | A client-supplied session id (§8) |
| The orchestrator's open CORS during the demo | — | The §8 fix, or the dummy-origin setting |
| The release tail is too long or too short | The end-clip test | Tune it; it's one constant |
| Chromium's noise suppression hurts recognition | Compare the same phrases with it on and off | Turn the flag off |
| During development, macOS grants permissions to the terminal or the Electron binary | The first run | Document it in the README |
| Packaging the uiohook native module | Later | Forge's auto-unpack-natives plugin |

---

## 11. Decisions — confirm or change

New in revision 4:
1. **Where speech-to-text runs:** in Electron's main process (recommended), or as a Python router inside the orchestrator.
2. **Provider switching:** a tray switch lasts until restart, and `.env` holds the defaults.
3. **Confirmations:** answered by voice (yes/no on the next take) or with buttons; no answer within 20 s counts as No.
4. **Build order:** the demo path P0–P3 first, then P4, then the optional P5.
5. **Spoken replies (P5):** off, unless you want them for the demo.

Carried over:
- Hold Right ⌥ as the hotkey.
- macOS only.
- The idle pill is always visible.
- Warm-mic window off.
- `mip_opt_out=true` on Deepgram requests.
- Providers: Deepgram (streaming), OpenAI and Sarvam (batch).
- Default Deepgram nova-3, falling back to Deepgram's batch mode.

---

## Appendix A. Echo review (revisions 2–3, updated for this design)

Echo is a reference only; no Echo code is copied.

**Ideas kept**
- The client owns the turn boundary.
- Stream while the user speaks, and send `Finalize` on commit, for a final text in about 150 ms.
- Keep the raw audio of every take for the fallback.
- Ignore takes under 200 ms.
- Custom vocabulary.
- Deepgram's quirks: it closes after about 10 s of silence, `KeepAlive` isn't first audio, and a second `Finalize` gets no reply.
- Retry once on 429 or 5xx only.
- Injectable vendor connections for offline tests.
- Provider and model picked as a pair.
- Vendor quirks in code: Sarvam's 28 s limit handled by splitting, Whisper's phrases filtered.
- Commit lessons:
  - the meter shows only audio that is sent (2bae1f9);
  - hand-offs happen in order (7771f87);
  - no speculative drafts (592feef).

**Drawbacks, and what Alfred does instead**

| Area | Echo does | Alfred instead |
|---|---|---|
| Capture | `ScriptProcessorNode` on the main thread, in 4096-sample chunks (about 85 ms) | AudioWorklet on the audio thread, 128-sample blocks |
| Capture | Downsamples by picking every n-th sample, with no filter | Chromium resamples into a 16 kHz context |
| Capture | Sends `commit` at once on release; up to about 0.1 s of buffered audio arrives afterwards and is dropped | A 200 ms release tail, with the last frame flushed before commit |
| Capture | A new stream and context on every start | One context for the app's lifetime; an optional warm-mic window with pre-roll |
| Capture | No device-change handling | Handles `devicechange` and track `ended`; sends what was captured; shows a message |
| Link | Silently drops audio and `commit` while the socket is closed; no reconnect | No socket between page and main (IPC); if the orchestrator is unreachable, the pill says so and keeps the transcript |
| Link | Control messages not tied to a turn (a blip's `cancel` once killed a turn in flight) | Take ids inside the main process; a cancel names its take |
| Link | Key or ticket in the URL | Vendor keys never leave the main process; the orchestrator token goes in a header |
| Streaming | One Deepgram connection per session; after one failure, every later turn falls back to REST (1–4 s each) | One connection per take |
| Streaming | Audio fed before the connection opens is dropped | Buffer from key-down; send the backlog on open; fall back if it never opens |
| Streaming | Audio sent from fire-and-forget tasks while `Finalize` is sent directly, so nothing guarantees their order | One send queue per connection |
| Streaming | Vendor `Error` messages ignored | Logged per take, with a short reason on the pill |
| Streaming | Streamed audio unmetered until a later fix | Seconds of audio logged per take and per provider |
| Streaming | No `mip_opt_out` | `mip_opt_out=true` |
| Providers | Two provider systems (live and bulk) with different model lists | One registry |
| Providers | Vendor picked partly by model prefix; unknown values silently go to OpenAI | Exact provider and model pair, validated; errors shown |
| Providers | `streaming` and `keyterms` shown for every vendor but used only by Deepgram | Providers declare their capabilities |
| Providers | Fallback only within the same vendor | A configurable fallback provider |
| Providers | Hard-coded, stale model lists | A curated menu plus custom model ids from `.env` |
| Providers | Vocabulary only for Deepgram | One vocabulary list, mapped per provider |
| Providers | Silence filtering only on the OpenAI path | A silence check before any vendor call |
| Hand-off | Over-long utterances trimmed to the last N seconds | Auto-send at 60 s; never trim |
| Hand-off | Turn state spread across one very large function | A small take object, plus one first-in-first-out command queue, both tested |

## Sources

- Orchestrator on `origin/main` (8ac66e4):
  - `orchestrator/main.py`, `engine.py`, `schemas.py`, `events.py`, `config.py`, `db.py`, `agents/base.py`
  - `test_cli.py`, `SUMMARY.md`, `docs/EXTENDING.md`
  - `alfred-orchestration-engine-spec.md`, `alfred-vision-and-architecture.md`
- Echo, used as reference:
  - `packages/echo-voice/src/audio/mic.ts`, `src/core.ts`, `src/transport.ts`
  - `api/app/stt_live.py`, `api/app/stt_local_stream.py`
  - `api/app/voiceflow.py`, `api/app/providers.py`, `api/app/vault.py`
  - commits 2bae1f9, 7771f87, 592feef
- [Electron #46143: Web Speech API fails with "network error"](https://github.com/electron/electron/issues/46143)
- [Electron #7749: webkitSpeechRecognition and Google API keys](https://github.com/electron/electron/issues/7749)
- [Electron globalShortcut](https://www.electronjs.org/docs/latest/api/global-shortcut)
- [pqp #751: native global push-to-talk hook for Electron](https://github.com/rafaelcg/pqp/pull/751)
- [uiohook-napi](https://github.com/SnosMe/uiohook-napi)
- [mockingbird #9: hold Fn to talk on macOS](https://github.com/NirjharBhattacharjee/mockingbird/pull/9)
- [Wispr Flow: keyboard shortcuts](https://docs.wisprflow.ai/articles/2612050838-supported-unsupported-keyboard-hotkey-shortcuts)
- [Electron window options (`type: 'panel'`)](https://www.electronjs.org/docs/latest/api/structures/base-window-options)
- [Web Audio: MediaStream into a context with a different sample rate (issue #2322)](https://github.com/WebAudio/web-audio-api/issues/2322)
- [Deepgram Model Improvement Partnership Program](https://developers.deepgram.com/docs/the-deepgram-model-improvement-partnership-program)
- [Sarvam streaming speech-to-text](https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/streaming-api)
