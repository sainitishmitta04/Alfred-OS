# TASK SPECIFICATION: "Charlie" Fast Desktop Agent Orchestrator

## Overview
We are building a lightweight, ultra-fast background AI agent backend for "Charlie" (a personal desktop assistant). 
The agent MUST NOT rely on visual screenshot analysis, mouse coordinate clicking, or vision models. 
Instead, it must use a **Tool-Calling Architecture** powered by a fast text LLM (Claude 3.5 Haiku or GPT-4o Mini) that executes desktop chores quietly in the background without stealing active mouse/window focus.

---

## Architectural Principles
1. **Zero Focus Interruption:** The agent runs headless tools (AppleScript/PowerShell OS controls, headless browser scripts, local file operations, or REST APIs). The user can keep working on their laptop in the foreground while Charlie executes chores in parallel.
2. **Sub-Second Latency Target:** Response times must stay under 500ms for decision-making by returning minimal JSON tool execution payloads.
3. **Async Non-Blocking FastAPI Server:** Long-running or multi-step agent requests must use async handlers or FastAPI `BackgroundTasks` so the API client receives immediate status receipts.

---

## Technical Stack
- **Framework:** FastAPI + Pydantic v2
- **Agent Model Engine:** Anthropic Python SDK (`claude-3-5-haiku-20241022`) or OpenAI Async SDK (`gpt-4o-mini`)
- **Async Runtime:** `asyncio` + `httpx` + Playwright Async API
- **OS Control Channel:** `subprocess` running native AppleScript (`osascript`) on macOS or PowerShell on Windows

---

## Required File Structure to Generate

backend/
├── app/
│   ├── main.py                # FastAPI entry point & routers
│   ├── schemas.py             # Pydantic request/response models
│   ├── agent/
│   │   ├── engine.py          # LLM Tool-calling orchestrator loop
│   │   └── prompts.py         # System prompt definitions
│   └── tools/
│       ├── desktop_control.py # AppleScript/OS background tools
│       ├── web_browser.py     # Headless Playwright automation tools
│       └── system_utils.py    # Local file and system utilities
├── .env.example
└── pyproject.toml / requirements.txt

---

## System Prompt Definition
The agent system prompt should explicitly enforce direct execution:
> "You are Charlie, an ultra-fast desktop assistant agent. Your primary objective is to execute user requests efficiently in the background without stealing screen focus or interrupting the user's active workflow. Always select the specific tool designed for the requested operation. Execute tools in parallel when possible and avoid verbose conversational chatter."

---

## Tool Implementations Needed

1. `control_media_player(action: str, track_or_playlist: Optional[str])`
   - Executes background AppleScript commands to control Spotify/Apple Music without switching active window focus.

2. `headless_web_scrape(url: str, action: str, selector: Optional[str], input_value: Optional[str])`
   - Spawns a background `playwright.async_api` browser instance (headless=True) to extract web text or fill web forms silently.

3. `execute_system_script(command_type: str, args: dict)`
   - Runs background system actions like setting volume, checking battery status, or listing local project files via fast shell calls.

---

## API Endpoints Required

1. `POST /api/v1/agent/execute`
   - Sync request/response endpoint for instant commands (e.g. "Pause Spotify", "Get battery status"). Returns final tool outcome immediately.

2. `POST /api/v1/agent/task`
   - Async endpoint for longer tasks (e.g., "Scrape summary from website and write to local file"). Uses `BackgroundTasks` to return a `task_id` receipt immediately while processing in the background.

3. `GET /health`
   - Health check endpoint returning system status and connected tool availability.

---

## Instructions for Code Generation
Generate production-ready Python code adhering to modern async patterns (Python 3.11+), explicit Pydantic type annotations, complete error handling for subprocess execution, and clean separation between API routes and tool execution logic.
