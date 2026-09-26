# 🦇 Alfred OS — Pitch (Opus Build Day · Everyday track)

> *"Every hero needs an Alfred."*

**Format:** about 1 min of slides and about 2.5 min of live demo, then Q&A.
**Slides:** open `docs/pitch/PITCH.html` in a browser. Use ← → or Space to move, **F** for fullscreen and **N** for speaker notes.

---

## Slide 1 — Title (15s)
**On screen:** Bat-signal · **ALFRED OS** · *"Every hero needs an Alfred."* · *Talk to your Mac. It acts, and shows every step.*

**Say:**
> "Batman never clicks through menus. He says what he needs and Alfred handles it. Every AI assistant today can *talk*. Alfred *acts*. Hold a hotkey, say one sentence, and it controls your Mac, browses the web and manages your files, and it shows you every step it takes. Let me show you."

→ **Switch to the live demo.**

---

## Live demo (about 2.5 min) — "The Batcave"
Press **Alt+Space**, speak, and tap again to stop. Keep the overlay and the **Tasks window** visible.

| # | Say | Point out |
|---|---|---|
| 1 | "Set the volume to 30" | Jev routes it to **direct** in about 150 ms. The overlay shows *Routed in … · Agent done in …*. |
| 2 | "Go to Hacker News, get the top 3 stories, then find more about the first one" | The **browser agent** plans 2 sub-tasks. Steps stream live: navigate → read → Jev check → search → summary. |
| 3 | "Delete the old screenshots in my Downloads folder" | Alfred **stops and asks**. Answer out loud: "**yes**". The desktop agent finishes inside its sandboxed folders. |
| (bonus) | Give 2 commands back to back | Both run as **background tasks** with toasts. Questions line up in a queue. |

End on #3. The confirmation moment is the one people remember.

**Mic-less fallback:** `ALFRED_PREVIEW_WAV=demo.wav` runs a recorded clip through the real pipeline.

---

## Slide 2 — "The Utility Belt": architecture (30s)
```
Alt+Space → 🎙 Deepgram nova-3 (India endpoint) → Orchestrator (FastAPI)
                                   │
                    Jev router  ~150 ms  (Choice + destructive Noul)
                    └─ confidence < 0.6 → Claude Haiku 4.5 → offline keywords
                                   │
        ┌───────────────┬──────────┴─────┬────────────────┐
     ⚡ Direct       🌐 Browser        🖥 Desktop        📓 Knowledge
   (one-shot OS)  Gemini Flash +     Claude Haiku      (Obsidian —
                  Playwright MCP     tool loop, files,  next up)
                  + any MCP          media, AppleScript
                                   │
          SSE live log · SQLite audit trail · Electron overlay + Tasks window
```

**Say:**
> "Two kinds of models, each doing what it's best at. Jev, a typed decision model, answers 'which agent?' and 'is this destructive?' in about 150 milliseconds. The large models do the real work inside each specialist agent. That's why it feels fast."

---

## Slide 3 — "Jev: the detective" (20s)
Jev makes **every quick decision**:
- **Routing:** a `Choice` over the agent descriptions, so new agents become routable automatically
- **Safety:** a `Noul` asking whether the request is destructive, in the same call
- **Inside the browser:** does this need several steps? Did that click work? Are we done or stuck? Is this click irreversible?
- **Afterwards:** was the goal actually satisfied?

**Say:**
> "Most agents spend a full LLM call on every yes-or-no question. Alfred asks Jev and gets a typed answer with a confidence score in milliseconds. It only escalates to Claude when Jev is unsure."

---

## Slide 4 — "The Code": trust & safety (20s)
- ✋ **Confirmation before anything irreversible:** checked up front on the whole request, and again mid-task on the actual button being clicked
- 🗣 **Answer by voice:** only a whole "yes" or "no" counts, and pending questions **expire after 10 minutes**, so a late "yes" can't run an old command
- 🔒 **Sandboxed:** file access is limited to Desktop, Documents and Downloads, and unsafe browser tools are blocked
- 👁 **Transparent:** every step is live on screen and logged to SQLite, with its latency
- 🛡 **Never crashes:** Jev → Claude → keywords, and model rotation. Failures turn into a spoken-friendly message.

**Say:**
> "Alfred has a code, just like Batman. It never does something irreversible without asking, and it never hides what it's doing."

---

## Slide 5 — "Built for the League": extensibility (15s)
- Add an agent **without touching the core:** `AGENT_OVERRIDES`, a pip entry point, or a file drop
- Add **any MCP server** to `mcp_servers.json` and the browser agent can use its tools
- Any agent can **pause mid-task** (`ConfirmationRequired`) and resume on approval
- Tested: about **69 Python tests** and **8 JS tests**

---

## Slide 6 — Close (10s)
**On screen:** *"Fast when it's obvious. Careful when it matters. Transparent always."* · Next: Knowledge agent (Obsidian) · spoken replies (TTS) · wake word

**Say:**
> "Alfred OS. Every hero needs an Alfred, and now everyone can have one. Thank you."

---

## Backup slide
A screen recording of a full run, `docs/pitch/demo.mp4`. If you need it, say:
> "Gotham Wi-Fi isn't on our side. Here's a recorded run."

---

## Q&A prep
- **Why Jev *and* Claude?** Jev gives a typed answer with a confidence score in about 150 ms. Below 0.6 confidence we ask Claude Haiku. If both are down, an offline keyword router keeps us running.
- **Why a router plus specialists instead of one big agent?** Small toolsets mean fewer wrong tool picks, and three people could build in parallel.
- **Which models?**
  - Routing: Jev, with Claude Haiku 4.5 as fallback.
  - Desktop agent: Claude Haiku 4.5.
  - Browser agent: Gemini Flash free tier, with OpenRouter free models as fallback (cheap and fast for long browsing loops).
- **What stops harmful actions?** The Jev destructive check, per-click risk checks with a keyword backstop, a filesystem sandbox, a browser tool deny-list, and expiring voice confirmations.
- **What if a model is rate-limited?** It rotates models and providers with backoff, and a model out of daily quota is skipped for the day.
- **What's mocked?** The Knowledge (Obsidian) agent is next. Its interface and routing already exist. Replies are shown on screen; spoken replies (TTS) are the next step.

## Honest gaps (know them before judges ask)
- Knowledge/Obsidian agent is still a mock
- No TTS yet (replies are on screen)
- Native desktop actions are macOS only
- Free-tier model quotas: have a paid key or a recording ready

## Pre-stage checklist
- [ ] Orchestrator running (`uvicorn orchestrator.main:app --port 8000`), Electron app open, one warm-up command done
- [ ] Playwright browser warmed up (run one browser command first)
- [ ] Mic tested with Alt+Space, and `ALFRED_PREVIEW_WAV` ready as a fallback
- [ ] Demo files in place (old screenshots in ~/Downloads for demo #3)
- [ ] Backup recording at `docs/pitch/demo.mp4`
- [ ] Roles: one speaker, one driver; each person takes Q&A on their own agent
