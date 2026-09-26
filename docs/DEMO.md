# Alfred demo guide

How to set up, check and present the Alfred demo on a Mac. Every command in the checklist below was run end to end on 2026-09-26; the times are from those runs.

## 1. One-time setup

```bash
cd ~/dev/Alfred-OS
uv sync                                   # orchestrator + agents (Python)
cp .env.example .env                      # then fill in the keys below
(cd app && npm install)                   # the Electron app
npx -y @playwright/mcp@0.0.82 install-browser chrome-for-testing   # browser agent, once
```

Keys in `.env`:

| Key | Used by | Without it |
|---|---|---|
| `DEEPGRAM_API_KEY` | Speech-to-text (India endpoint by default) | Nothing can be heard |
| `ANTHROPIC_API_KEY` | Desktop agent, Claude fallback routing | Desktop and `direct` commands fail |
| `TYPESAFE_API_KEY` | Jev routing, risk checks and verification | Routing falls back to keywords |
| `GEMINI_API_KEY` or `OPENROUTER_API_KEY` | Browser agent | Browser commands fail |

- **The Anthropic key must be scoped to one workspace.** In platform.claude.com, open **API keys → Create key** and set **Scope** to a workspace (for example Default). A key scoped to the organization is rejected unless every request names a workspace, and our code doesn't do that.
- **The desktop agent's model** must be `ALFRED_AGENT_MODEL=claude-haiku-4-5-20251001`. The older default, `claude-3-5-haiku-20241022`, is retired.
- **If port 8000 is taken** on your Mac (Docker or Colima often use it), set `ORCHESTRATOR_URL=http://127.0.0.1:8700`.

## 2. Start

```bash
cd ~/dev/Alfred-OS/app && npm start
```

- **"Alfred" appears in the menu bar.** The app starts the orchestrator itself if it isn't already running, which takes about 6 s.
- **Open the tray menu and check the first status line.** It should read `Orchestrator online · direct, browser, desktop · Jev`. If it says offline, see Troubleshooting.
- **The first recording asks for microphone access for "Electron".** Allow it.

**Controls:**
- Tap **⌥Space**, speak, then tap **⌥Space** again to send.
- **Esc** cancels a recording.
- **Tray ▸ Show tasks** opens the task list.

## 3. Pre-demo check (5 minutes)

Run these in order. Each line says what you should see.

| # | Say | Expect | Seen in testing |
|---|---|---|---|
| 1 | Tap ⌥Space, then press Esc | The pill turns yellow with moving bars, then closes. Nothing is sent | ✓ |
| 2 | "Lower the volume" | Toast "On it", then "Volume lowered to …" with chips `direct · Jev · 0.98`, STT, agent and total times. The Mac's volume really drops | 3.2 s |
| 3 | "Open the Calculator app" | Calculator opens; the toast says it's opening | 4.2 s |
| 4 | "What is the latest stable Python release?" | "On it" right away; the answer arrives in the background ("Python 3.14.x") | 17.8 s |
| 5 | "Delete the old screenshots on my desktop", then say or click **No** | Question card "This looks irreversible…", then "Okay, I won't do that." | ✓ |
| 6 | Tray ▸ Show tasks | Every task listed, newest first. Click a row to see its steps, answer and latencies | ✓ |

For item 5, say **No**. A **Yes** really deletes files: the desktop agent can delete in Desktop, Documents and Downloads. To demo a yes, use the dummy folder in section 4.

## 4. Demo script (about 3 minutes)

1. **Voice, routing and latency.** Say "Lower the volume". Point at the chips: speech-to-text time, Jev routing time, agent time, total.
2. **It really controls the Mac.** Say "Open the Calculator app".
3. **Tasks run in the background.** Say "What's the latest stable Python release?" and, while it's still running, "Open TextEdit".
   - Open **Show tasks**: the browser task is still running with live steps, while TextEdit has already opened.
4. **Safety.** Prepare the dummy folder first (run this before the demo):

   ```bash
   mkdir -p ~/Desktop/"Alfred Demo" && for i in 1 2 3; do echo x > ~/Desktop/"Alfred Demo"/"Screenshot $i.png"; done
   ```

   - Say "Delete the screenshots in the Alfred Demo folder on my desktop". Jev flags it as destructive and the question card appears.
   - Say "yes" (tap ⌥Space, "yes", ⌥Space) or click **Yes, do it**. The three files are deleted; anything else in the folder stays.
   - Known issue: the card may turn red ("failed") even though the deletion worked. That happens when one of the agent's tool calls failed before it recovered (see section 6).
5. **Close.** In Show tasks, expand the delete task to show the question, your answer, each file step and Jev's check.

## 5. Rehearsing without a mic, and a backup video

- **Feed a recorded phrase through the real pipeline:**

  ```bash
  say -o ~/take.wav --data-format=LEI16@16000 "Lower the volume"
  cd ~/dev/Alfred-OS/app && ALFRED_PREVIEW_WAV=~/take.wav npm start
  ```

- **Record a backup video** of a good run with **⌘⇧5 → Record Entire Screen**, in case the live demo fails.

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| ⌥Space does nothing | Another app owns ⌥Space (the ChatGPT app does). Set `HOTKEY=Control+Alt+Space` in `.env` and restart |
| "Microphone blocked" | System Settings → Privacy & Security → Microphone → allow **Electron** |
| Tray says "Orchestrator offline" | Check `~/Library/Application Support/alfred-voice/orchestrator.log`, or start it by hand: `uv run uvicorn orchestrator.main:app --port 8000` from the repo root |
| Tray says the port "is used by another app" | Set `ORCHESTRATOR_URL=http://127.0.0.1:8700` in `.env` |
| Desktop commands answer "hit an error" | Test the Anthropic key; a scope error means it's an organization key (see section 1). Also check `ALFRED_AGENT_MODEL` |
| Browser answers "quota used up" | The free OpenRouter tier allows 50 requests a day. Add a Gemini key, or credits |
| "Didn't catch that" | Start speaking after the bars appear, and tap ⌥Space again after you finish |
| A card is red although the action worked | Known desktop-agent issue: a task counts as failed if any tool call failed, even after the agent recovered (`desktop_use/orchestrator_agent.py`) |
