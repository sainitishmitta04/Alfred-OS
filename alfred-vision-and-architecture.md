# Alfred OS — Project Vision & Architecture (Read Me First)
Give this to Claude Code as the very first message, before any build spec, so it has full context on what we're building and why, before generating any code.

---

## 1. What this project is

**Alfred** is a voice-controlled AI agent that lives on your Mac and actually *does things* — not just answers questions. You talk to it, and it controls your computer, browses the web, manages your files, and reads/writes your personal notes. Built in one day for a hackathon (Anthropic's "Opus Build Day" in Bangalore), on the "Everyday" track: something that solves a real problem in daily computer use.

**The core pitch**: most AI assistants can only talk. Alfred can act — open apps, adjust system settings, search and summarize the web, edit your files, and manage your personal knowledge base, all from a single spoken sentence, and it tells you (in a live UI log) exactly what it's doing at each step, so it never feels like a black box.

## 2. Team & ownership
3 people, each owning a clear vertical slice:
- **Person A**: Trigger (hotkey) + STT pipeline, and the Knowledge Agent (Obsidian integration)
- **Person B (me)**: Orchestration Engine (the central router/brain) + the Browser Agent
- **Person C**: Desktop Agent (native macOS control + local file operations)

## 3. High-level architecture

```
Voice input (hotkey + STT)
        │
        ▼
Orchestration Engine  ◄── the central dispatcher. Decides which specialist
        │                  agent should handle each request, logs everything,
        │                  manages confirmation flow for risky actions.
        │
   ┌────┼────────────┬─────────────────┐
   ▼    ▼             ▼                 ▼
Direct  Browser Agent  Desktop Agent     Knowledge Agent
Command                                    
(native  Uses Playwright  Uses filesystem   Uses Obsidian MCP to
 OS      MCP + brave-      MCP + native      read/write/search
 action, search MCP to      macOS commands    the user's personal
 no       navigate/click/    (volume, open      notes vault
 agent    type/extract        apps, screenshots,
 needed)   web pages             file ops)
        │
        ▼
Response synthesized → spoken back (TTS) + shown in a live UI action log
```

## 4. Why this architecture (the reasoning Claude Code should internalize)

- **Router + specialist agents, not one giant tool list.** Each agent gets a small, focused toolset scoped to its domain. This makes tool selection more reliable (smaller schema = fewer mistakes) and makes the codebase easy to split across 3 people working in parallel without stepping on each other.
- **Two different AI models, used for what each is good at.** Claude Opus 5.5 does the actual reasoning inside each agent (multi-step tool use, understanding ambiguous requests, browsing loops). Jev (TypeSafe AI's "System One" model) does fast, typed, low-latency classification decisions — specifically, top-level routing ("which agent handles this?") and, inside the Browser Agent, per-step decisions ("does this page match the goal? did the last click succeed?"). Jev doesn't generate text; it returns a typed answer (Choice/Score/Boolean) with a confidence score, which is much faster than a full LLM call for yes/no or pick-one decisions. This lets the system skip expensive Claude calls on the "obvious" steps and only escalate to Claude when a decision is genuinely ambiguous (confidence below a threshold).
- **Existing, proven MCP servers wherever possible, custom code only where necessary.** We use official/community MCP servers for filesystem access, browser automation (Playwright), web search (Brave), and Obsidian vault access, rather than writing these integrations from scratch. Custom code is reserved for things no MCP server covers: native macOS control (volume, opening apps, media keys, screenshots, lock screen).
- **Everything is logged to SQLite as it happens**, not just at the end. Every routing decision and every agent step gets a row in the database in near-real-time. This isn't just for debugging — it directly powers the live "action log" panel in the UI, which is one of our most important demo features: the judges need to *see* Alfred thinking and acting step by step, not just hear a final answer. Transparency into what the agent is doing is also something Anthropic's own judges are likely to specifically value.
- **Confirmation before destructive actions.** Any action that could overwrite, delete, or otherwise irreversibly change something pauses and asks for explicit confirmation before executing. This is a deliberate safety/trust feature, not just a technical nicety — it's meant to visibly demonstrate responsible agent design.
- **Latency is tracked and shown, not hidden.** We separately measure and display how long the routing decision took versus how long the agent's actual work took. This turns a normal-looking assistant interaction into a visible technical story about smart model routing.

## 5. Tech stack (final decisions, don't relitigate these)
- **Orchestration Engine**: Python 3.11+, FastAPI, stdlib `sqlite3`
- **Routing model**: Jev (TypeSafe AI System One), via `typesafe-sdk` Python package, with confidence-threshold fallback to a quick Claude call when uncertain
- **Agent reasoning model**: Claude Opus 5.5, via `@anthropic-ai/sdk` or the Python Anthropic SDK, using `mcp_servers` for MCP-backed agents
- **Browser Agent**: Claude + `@playwright/mcp` (official Microsoft MCP server, uses accessibility-tree snapshots not screenshots) + Brave Search MCP, with a Jev-driven inner loop for per-step decisions
- **Desktop Agent**: Claude + `@modelcontextprotocol/server-filesystem` MCP + custom native tools (AppleScript-based) for volume/apps/screenshots/lock
- **Knowledge Agent**: Claude + community Obsidian MCP server (talks to the Obsidian Local REST API plugin)
- **UI**: Electron (renderer shows live transcript, action log, latency readout, confirmation prompts)
- **STT/TTS**: Web Speech API (browser-native, zero setup, good enough latency for a demo)
- **Platform target**: macOS only for this build (no cross-platform effort — pick one OS and make it reliable)

## 6. What "done" looks like for the hackathon (not a production roadmap)
This is a **2.5-hour build**, not a product launch. The bar is: a small number of voice commands work reliably, live, in front of judges, end-to-end, including at least one command that visibly chains multiple steps (e.g., find a file → read it → edit it → confirm) and one that uses the Browser Agent (e.g., fetch and summarize recent LinkedIn posts). Depth and polish on a few flows beats breadth across many half-working ones. A fallback screen-recording of a working run is captured as insurance in case live demo conditions fail.

## 7. What's explicitly out of scope for today
- Wake-word detection (push-to-talk hotkey only — more reliable in a noisy demo room)
- Cross-platform support (macOS only)
- Any live login/authentication performed on stage (all accounts pre-authenticated ahead of time)
- Payment or ticket-booking flows (too fragile to demo live)
- Arbitrary multi-hop agent chaining (cap at one handoff between agents for any single command)

## 8. My (Person B's) specific responsibility
I own two pieces:
1. **The Orchestration Engine** — the central Python/FastAPI service described above: receives transcripts, calls Jev to route, manages the destructive-action confirmation flow, dispatches to whichever agent (mocked initially, real once teammates finish theirs), logs everything to SQLite, and returns a structured response for the UI to speak and display.
2. **The Browser Agent** — a Claude-powered agent using Playwright MCP + Brave Search MCP, with an internal loop where Jev makes fast per-step decisions (does this element match the goal, did the action succeed, is the goal complete) and only escalates to a full Claude reasoning call when Jev's confidence is low.

I'll give you the detailed build spec for the Orchestration Engine next, followed by the Browser Agent spec. This document is just the shared context — read and confirm your understanding of the architecture and reasoning above before we start generating code, since every module we build from here needs to fit into this design.
