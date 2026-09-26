# Extending the Alfred Orchestration Engine

You never need to edit `engine.py` or `router.py` to add capabilities. Pick one of the paths below.

## 1. Add or replace an agent

### a) Simplest: a plain async function (the spec's interface)
```python
# my_team/desktop.py
async def run_desktop_agent(goal: str) -> str:
    """Requires local file read/search/write, screenshots, or app-launching tied to file content."""
    ...
    return "Moved 3 files to Archive."
```
```bash
# .env — shadows the mock with the same name
AGENT_OVERRIDES=desktop=my_team.desktop:run_desktop_agent
```
The docstring becomes the routing description (if omitted, the mock's description is kept).

### b) Log live steps to the UI: accept `ctx`
```python
async def run_browser_agent(goal: str, ctx) -> str:
    ctx.step("navigate", "https://linkedin.com/feed")
    ctx.step("extract", "5 posts found")
    return "Here's a summary of your last 5 posts..."
```

### c) Full control: subclass `Agent`
```python
from orchestrator.agents import Agent, AgentResult

class SpotifyAgent(Agent):
    name = "music"
    description = "Playing, searching, or queuing specific songs, artists or playlists"
    timeout_s = 15            # per-agent timeout
    always_confirm = False    # True = always ask before running

    async def startup(self):  # open MCP sessions / browsers once
        ...

    async def run(self, goal, ctx):
        ctx.step("search", goal)
        return AgentResult(text="Playing Daft Punk.", data={"track": "..."})
```
Register it with `AGENT_OVERRIDES=music=my_pkg.spotify:SpotifyAgent` **or** as a pip entry point:
```toml
[project.entry-points."alfred.agents"]
music = "my_pkg.spotify:SpotifyAgent"
```
A **new name becomes a new route automatically**: Jev's routing `Choice` is built from every
registered agent's `description`. Write descriptions as crisp routing criteria.

## 2. Hooks (cross-cutting behavior)
```python
from orchestrator.main import app

def clean_goal(state):            # before_dispatch can rewrite the goal
    state["goal"] = state["goal"].removeprefix("um ").strip()

app.state.orchestrator.add_hook("before_dispatch", clean_goal)
```
Events: `before_route`, `after_route`, `before_dispatch`, `after_dispatch`, `on_error`.
`state` holds `session_id`, `transcript`, `goal`, `decision` (RouteDecision), `result` (AgentResult), `error`.
Hooks may be sync or async; exceptions are logged to `errors` and never break the request.

## 3. Swap the router
Anything with `async def route(transcript, agents: dict[str, str]) -> RouteDecision` works:
```python
from orchestrator.engine import Orchestrator
engine = Orchestrator(settings, db, registry, router=MyRouter())
```

## 4. Embed without HTTP
```python
from orchestrator.config import get_settings
from orchestrator.main import build_orchestrator
engine, _ = build_orchestrator(get_settings())
result = await engine.handle_transcript("lower the volume")
```

## 5. Browser Agent: add MCP servers and tools

**Any MCP server** → add it to `mcp_servers.json`; its tools show up as `<server>__<tool>`:
```json
"github": {
  "command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"],
  "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_TOKEN}"},
  "enabled_if_env": "GITHUB_TOKEN"
},
"remote": {"url": "https://my-mcp.example.com/mcp"}
```
`${VAR}` expands from the env, `enabled_if_env` makes a server optional, and `args_if_env` adds flags conditionally.

**A Python tool:**
```python
from browser_agent import tool

@tool("weather", "Current weather for a city", {"city": {"type": "string"}}, ["city"], read_only=True)
async def weather(city: str, **_) -> str:
    ...
```
Import the module somewhere at startup, or expose a `ToolSpec` (or list of them) through the `alfred.browser_tools` entry point.
Tools that aren't read-only go through the Jev risk check automatically.

**Models and providers:**
- `LLM_PROVIDERS=gemini,openrouter` sets the provider order. A provider with no API key is skipped.
- `GEMINI_MODELS=gemini-3.8-flash,...` pins Gemini models. If it's empty, the newest Flash models are picked automatically.
- `GEMINI_REASONING_EFFORT=low|medium|high|none` sets how much the Gemini model "thinks" per step.
- `OPENROUTER_MODELS=model-a:free,...` sets the OpenRouter models, tried in order.
- All models must support tool calling.
- To add another OpenAI-compatible provider, subclass `OpenAICompatClient` in `browser_agent/llm.py` and add it to `build_llm`.
**Deny tools:** `BROWSER_TOOL_DENYLIST=playwright__browser_run_code_unsafe,...`
