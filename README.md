# 🦇 Alfred

**Your Mac, by voice.** Tap **⌥Space**, say what you want, and Alfred does it. It opens apps, writes your notes, organizes files, researches the web and fills in forms.

Every command runs in the background, and you can watch each step happen. Before anything irreversible, Alfred asks you first.

> Most AI assistants can only talk. Alfred acts, and shows its work.

Built in a day at Anthropic's **Opus Build Day** in Bangalore.

---

## ✨ What Alfred can do

| | Capability | Say something like |
|---|---|---|
| 🖥️ | **Control your Mac:** open and switch apps, volume, music | "Open the Calculator app" · "Lower the volume" · "Open the browser" |
| 📝 | **Notes and planning** in Apple Notes, Reminders and Calendar | "Open Apple Notes and make the daily plan for me" |
| 📁 | **Files:** create, write, search, move and sort, inside Desktop, Documents and Downloads | "Create a folder called Hackathon on my Desktop with an agenda.md inside" |
| 🌐 | **Research the web:** search, read pages, and break a big question into steps | "Compare the latest releases of Python and Node.js" |
| 🧾 | **Act on websites:** navigate, click, type and fill in forms | "Fill in the pizza order form on httpbin.org/forms/post for Alfred" |
| 🛡️ | **Ask before anything irreversible:** deleting, submitting, buying | "Delete the old screenshots on my desktop", then Alfred asks "Should I go ahead?" |
| ⚡ | **Run several tasks at once:** you keep talking while earlier commands finish | Ask three things in a row, then open **Show tasks** |

## 🚀 Impressive things to try

1. **The safety pause.** Say: *"Go to httpbin.org/forms/post, fill in the pizza order form for Alfred with a large pepperoni, and submit it."*
   - The browser fills in the form, then **stops before "Submit order"** and asks you.
   - Say "yes", and it finishes the task it paused.
2. **Plan my day.** Say: *"Create a note called Daily Plan with a morning, afternoon and evening schedule, and add reminders for standup at 10 and the demo at 4."*
   - Notes and Reminders fill in from a single sentence.
3. **Research with a plan.** Say: *"Compare the latest releases of Python and Node.js and tell me which came out more recently."*
   - The browser agent splits the question into sub-tasks, researches each one live, and answers in one line.
4. **Tidy up.** Say: *"Sort the files in the Alfred Demo folder on my desktop into folders by file type."*
   - Finder reorganizes itself while you watch. Try it on a demo folder first (see [docs/DEMO.md](docs/DEMO.md)).
5. **All at once.** Say #3, then *"Create a folder called Hackathon on my Desktop with an agenda.md inside"*, then *"Set the volume to 30 percent"*.
   - Open **Show tasks** and watch all three run in parallel.

---

## 🏁 Quick start

**You need:** a Mac (tested on Apple Silicon), [Node.js](https://nodejs.org) 20+, [`uv`](https://docs.astral.sh/uv/) (`brew install uv`), and the API keys below.

```bash
git clone https://github.com/sainitishmitta04/Alfred-OS.git && cd Alfred-OS
uv sync                                    # Python: orchestrator + agents
cp .env.example .env                       # then add your keys (table below)
(cd app && npm install)                    # the Electron app
npx -y @playwright/mcp@0.0.82 install-browser chrome-for-testing   # browser agent, once

cd app && npm start                        # starts Alfred (and the orchestrator)
```

**Alfred** appears in your menu bar. The first recording asks for microphone access for "Electron"; allow it.

| Key in `.env` | What it powers |
|---|---|
| `DEEPGRAM_API_KEY` | Speech-to-text (India endpoint by default) |
| `ANTHROPIC_API_KEY` | Claude for the desktop and browser agents. Use a key **scoped to one workspace** (platform.claude.com → API keys → Scope) |
| `TYPESAFE_API_KEY` | Jev: routing, risk checks and result checks |
| `GEMINI_API_KEY` / `OPENROUTER_API_KEY` | Optional fallback models for the browser agent |

> If port 8000 is taken on your Mac (Docker and Colima often use it), set `ORCHESTRATOR_URL=http://127.0.0.1:8700` in `.env`.

## 🎙️ Using Alfred

| To | Do this |
|---|---|
| **Talk** | Tap **⌥Space**, speak, then tap **⌥Space** again to send |
| **Cancel** | Press **Esc** while recording |
| **Answer a question** | Click **Yes, do it** or **No**, or tap ⌥Space and say "yes" or "no" |
| **See all tasks** | Menu bar → **Alfred** → **Show tasks**. Clicking any "done" toast also opens it, or start with `ALFRED_SHOW_TASKS=1 npm start` |

**The overlay** sits at the bottom of the screen and never takes focus.
- It shows yellow bars while you talk.
- After you send, it says **"On it"** and gets out of the way.
- It comes back with a done toast, or with a question if a task needs your approval.

**The Tasks window** lists every command, newest first. Each row shows:
- its status: running, needs you, done or failed;
- the agent that handled it;
- live steps as they happen;
- the answer;
- latency chips for speech-to-text, routing, the agent and the total.

**The tray menu** shows whether the orchestrator is online and which agents are loaded. It also switches the speech-to-text provider (Deepgram or OpenAI) and opens `.env`.

---

## 🧠 How it works

```
 ⌥Space ─► 🎙️ Electron overlay ─► speech-to-text (Deepgram nova-3, India endpoint)
                                        │ text
                                        ▼
              ┌──────────── Orchestrator (FastAPI) ────────────┐
              │ Jev routes each command to one agent (~0.5 s)  │
              │ Jev flags destructive actions → asks you first │
              │ every step → SQLite + a live event stream      │
              └───────┬───────────────────────────┬────────────┘
                      ▼                           ▼
        🖥️ Desktop agent                 🌐 Browser agent
        Claude Haiku 4.5                 Claude Opus 5 (+ Gemini / OpenRouter fallback)
        AppleScript, files, music        web search, page reading, Playwright browser
                                         pauses before risky clicks (Jev risk check)
                      │                           │
                      └──── steps & answers ──────┴──► Tasks window + overlay toasts
```

- **Commands run in the background.** `POST /tasks` answers straight away, and the UI follows each task through live events. A two-minute browser task never blocks the next command.
- **Two models, each used for what it's good at.** Jev (TypeSafe) makes fast typed decisions: which agent, whether an action is risky, whether the goal was met. Claude does the multi-step work inside each agent.
- **Nothing irreversible runs without you.**
  - A destructive command pauses before it starts.
  - The browser agent pauses before submitting, buying, sending or deleting.
  - Only a clear "yes" or "no" answers: "okay, open Safari" starts a new task instead of approving the pending one.
  - Questions expire after 10 minutes.

### Measured on the demo Mac

| Command | Route | Result | Total |
|---|---|---|---|
| "Lower the volume" | direct → desktop agent (Jev 0.98) | Volume 100 → 50 | 3.2 s |
| "Open the Calculator app" | direct → desktop agent (Jev 1.00) | Calculator opened | 4.2 s |
| "What is the latest stable Python release?" | browser (Jev 1.00, Claude Opus 5) | "Python 3.14.7" | 5.0 s |
| "Please open Apple Notes and make the daily plan for me" | desktop (Jev 1.00) | "Daily Plan" note created | 18 s |
| "Delete the old screenshots on my desktop" | desktop (Jev destructive 0.97) | Asked first; declined → nothing deleted | 0.8 s to the question |

Speech-to-text on Deepgram's India endpoint took about 0.6 s per command.

---

## 📂 Project layout

| Path | What |
|---|---|
| `app/` | Electron app: hotkey, recording, speech-to-text, overlay, Tasks window, tray |
| `orchestrator/` | FastAPI engine: Jev routing, confirmations, background tasks, SQLite log, live events |
| `desktop_use/` | Desktop agent: Claude tool loop with AppleScript, file and media tools |
| `browser_agent/` | Browser agent: Claude, Gemini or OpenRouter, with MCP tools and Jev decisions |
| `direct_agent.py` | Sends one-shot native commands ("open Calculator") to the desktop agent |
| `docs/DEMO.md` | Demo guide: pre-demo checklist, script, troubleshooting |

## 🛠️ For developers

```bash
uv run uvicorn orchestrator.main:app --port 8000     # orchestrator only
python test_cli.py "lower the volume"                 # try it without the app
uv run pytest -q                                      # orchestrator + agents (offline)
(cd app && npm test)                                  # app logic (offline)
```

- **Plug in a new agent without touching the engine:** see [docs/EXTENDING.md](docs/EXTENDING.md).
- **Engine internals:** [SUMMARY.md](SUMMARY.md).
- **Desktop agent file access:** limited to Desktop, Documents and Downloads. Change it with `DESKTOP_FS_ALLOWED_DIRS` (colon-separated paths).
- **Standalone desktop API:** the orchestrator runs the desktop agent in-process, so it's optional; it listens on port 8787 if you start it.

**Something not working?** See the troubleshooting table in [docs/DEMO.md](docs/DEMO.md#6-troubleshooting).
