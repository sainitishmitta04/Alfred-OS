# Alfred desktop-use backend

FastAPI service that runs Alfred as a background tool-calling agent (Anthropic Haiku) for desktop chores without focus-stealing UI automation.

## Setup

```bash
cd desktop-use/backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# Add ANTHROPIC_API_KEY to .env (local only; do not commit)
playwright install chromium
```

## Run

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8787
```

## API

- `GET /health` — service and tool availability
- `POST /api/v1/agent/execute` — synchronous agent run
- `POST /api/v1/agent/task` — enqueue background task (returns `task_id`)
- `GET /api/v1/agent/task/{task_id}` — poll task status

## Tests

```bash
pytest
```
