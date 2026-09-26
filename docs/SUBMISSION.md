# Alfred OS: Opus Build Day submission answers

> Draft answers for the submission form. Items marked **⚠️ YOU DECIDE** need your own answer.
> Don't let anyone accept them on your behalf.

---

## What is your project?
**Alfred OS: a voice-controlled AI agent that *acts* on your Mac, and shows you every step it takes.**

Hold Alt+Space and say one sentence, like "go to Hacker News, get the top 3 stories and find more about the first one," or "delete the old screenshots in my Downloads folder." Alfred does it.

A fast typed-decision model (Jev) routes each request in about 150 ms to a specialist agent:
- **Browser agent:** web search, plus real browsing through Playwright MCP and any other MCP server
- **Desktop agent:** files, media and AppleScript
- **Direct commands:** one-shot actions like volume
- **Knowledge agent:** for Obsidian notes (in progress)

Every step streams live into an on-screen action log and is saved to SQLite. Before anything irreversible, Alfred stops and asks, and you can answer "yes" or "no" out loud.

**Who it's for:** anyone who spends their day clicking through apps, tabs and folders, and anyone who wants an AI agent they can actually *trust* with their computer.

**Problem it solves:** most assistants can only talk. The agents that do act are black boxes that might do something irreversible without asking. Alfred acts, stays transparent the whole time, and keeps the human in control.

---

## How did Claude contribute?
Claude was both our **build partner** and a **model running inside the product**.

- **Building it:** we built Alfred with **Claude Code running Claude Opus 5.5**, working in a plan-first loop.
  - It designed and wrote the orchestration engine (FastAPI, Jev routing with fallbacks, the confirmation flow, the SQLite audit log, the live SSE event stream) and the browser agent (planner, MCP tool pool, Jev per-step checks, pause and resume for risky clicks).
  - It wrote around 70 tests, debugged live problems (a headless browser crashing on a font-less Linux server, Gemini 3's `thought_signature` requirement, free-tier rate limits), wrote the docs, and pushed the commits.
  - Teammates also used Claude to build the voice pipeline and the desktop agent.
- **Inside Alfred:**
  - **Claude Haiku 4.5** powers the desktop agent's tool-use loop.
  - Claude Haiku 4.5 is also the **fallback router**: when Jev's confidence drops below 0.6, a quick forced-choice Claude call picks the agent.

**Model used:** Claude Opus 5.5 (via Claude Code) for building. Claude Haiku 4.5 at runtime.

---

## Did you build using Anakin?
**⚠️ YOU DECIDE:** Yes / No. Nothing in the codebase references Anakin, so answer based on what you actually used.

---

## What's your biggest takeaway from today?
> "Don't make your smartest model answer every question. Let a fast model make the yes-or-no calls in milliseconds, and save the big model for real thinking. That one split made Alfred feel instant *and* made it safer."

---

## What would you tell someone who's never tried this?
> "Plan first, then build in small verified steps, and test against the real thing early. Our biggest bugs, a browser crashing because the server had no fonts and an API needing a hidden signature echoed back, only showed up in live runs. Claude found and fixed them in minutes once we actually ran it."

---

## Anything else you want to tell us about your project?
**Inspiration:** Batman never clicks through menus. He tells Alfred what he needs. We wanted everyone to have that: an assistant that doesn't just answer but gets things done, and one you can trust because it never hides what it's doing.

**How we built it:** a team of 3, each owning one area:
- voice and hotkey input plus the Knowledge agent
- the orchestration engine plus the browser agent
- the desktop agent

The orchestrator's plug-in design (agents registered through config or entry points, routing built from each agent's description) meant all three of us could build in parallel and merge without conflicts.

**What we're proud of:**
- Routing in about 150 ms, falling back to Claude and then to an offline keyword router, so it never crashes
- Any agent can pause mid-task for approval, and voice confirmations expire after 10 minutes
- Commands run as parallel background tasks
- Any MCP server plugs in with one config line
- The browser agent runs on free models

**Honest status:** the Knowledge (Obsidian) agent and spoken replies (TTS) are next.

**Third-party components** (for the IP attestation):
- **Open-source software:** Playwright MCP (Microsoft), the MCP Python SDK, FastAPI, Electron, the OpenAI Python SDK (used as the client for Gemini and OpenRouter), and ddgs (DuckDuckGo search). All are used under their licenses.
- **External APIs:** TypeSafe AI (Jev), Anthropic (Claude), Google Gemini, OpenRouter, and Deepgram (speech-to-text).

---

## Link to your project
https://github.com/sainitishmitta04/Alfred-OS
*(Check that the repo is **public** before submitting.)*

---

## What are you sharing?
**⚠️ YOU DECIDE:** tick whatever you actually have. Suggested:
- [ ] A video of it in action (screen recording): the strongest option. Use the 3-command demo.
- [ ] Close-up / detail shots (UI): action log, confirmation prompt, Tasks window
- [ ] A photo of me with my build
- [ ] A group or team photo
- [ ] Behind-the-scenes / process shot
- [ ] Other: pitch deck (`docs/pitch/PITCH.html`)

## Screenshots / videos
Upload (10 MB limit) a short clip or screenshot of the overlay mid-task showing the live steps and the "Should I go ahead?" prompt.

## Links to additional media
**⚠️ YOU DECIDE:** add a Google Drive or Dropbox link to the full demo recording, if you have one.

---

## Preferred attribution
**⚠️ YOU DECIDE:** e.g. *Sai Nitish Mitta · GitHub @sainitishmitta04* (plus teammates' names and handles, and any socials you want credited).

---

## Consent to be contacted / Consent to feature / IP attestation
**⚠️ YOU DECIDE: these are legal agreements. Read them and accept them yourself.**

Before accepting:
- **Feature consent** is perpetual and irrevocable. Make sure everyone who appears in your photos or videos agrees, and that **teammates are OK being featured**.
- **IP attestation:** list the third-party components above in the "Anything else" field, and confirm you're authorized to submit on behalf of the team.
- Don't include API keys, `.env` contents, or personal data in any screenshot or video.
