# Alfred-OS

Voice-controlled macOS agent. This repo currently holds the **Orchestration Engine** (`orchestrator/`).

```bash
cd /path/to/Alfred-OS
uv sync                                   # creates .venv and installs deps
cp .env.example .env                      # ANTHROPIC_API_KEY for desktop; TYPESAFE optional

# Use the project env (do not use Homebrew uvicorn — it has no project deps):
uv run uvicorn orchestrator.main:app --reload --host 127.0.0.1 --port 8000
# or: source .venv/bin/activate && uvicorn orchestrator.main:app --port 8000

python test_cli.py "lower the volume"
uv run pytest -q
```

See [SUMMARY.md](SUMMARY.md) for the overview and [docs/EXTENDING.md](docs/EXTENDING.md) to plug in agents.

The **desktop** route uses the Haiku tool agent in `desktop_use` (filesystem + native tools). Set
`ANTHROPIC_API_KEY` in `.env`. Optional: `DESKTOP_FS_ALLOWED_DIRS` (colon-separated paths). You only need
`uvicorn orchestrator.main:app` — no separate desktop-use server unless you want the standalone API on port 8787.
