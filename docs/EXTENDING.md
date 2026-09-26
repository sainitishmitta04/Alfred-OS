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
