# Alfred desktop-use backend

FastAPI service that runs Alfred as a background tool-calling agent (Anthropic Haiku) for desktop chores without focus-stealing UI automation.

When used with the Alfred orchestrator (`uvicorn orchestrator.main:app`), the **`desktop`** agent imports this
package in-process via `desktop_use.orchestrator_agent` — you do not need this server unless you want the HTTP API.

## Setup

```bash
cd desktop_use
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# Add ANTHROPIC_API_KEY to .env (local only; do not commit)
playwright install chromium
```

## Run

```bash
uv run uvicorn desktop_use.main:app --reload --host 127.0.0.1 --port 8787
```

## API

- `GET /health` — service and tool availability
- `GET /api/v1/tools` — tool schemas (for Haiku + manual testing)
- `POST /api/v1/tools/{tool_name}/invoke` — run one tool directly (no LLM)
- `POST /api/v1/agent/execute` — synchronous agent run
- `POST /api/v1/agent/task` — enqueue background task (returns `task_id`)
- `GET /api/v1/agent/task/{task_id}` — poll task status

### Invoke tools directly (examples)

```bash
curl -s -X POST http://127.0.0.1:8787/api/v1/tools/execute_system_script/invoke \
  -H 'Content-Type: application/json' \
  -d '{"arguments":{"command_type":"battery_status"}}' | jq

curl -s -X POST http://127.0.0.1:8787/api/v1/tools/control_volume/invoke \
  -H 'Content-Type: application/json' \
  -d '{"arguments":{"action":"get"}}' | jq

curl -s -X POST http://127.0.0.1:8787/api/v1/tools/get_system_info/invoke \
  -H 'Content-Type: application/json' \
  -d '{"arguments":{}}' | jq
```

## Tests

```bash
pytest
```
