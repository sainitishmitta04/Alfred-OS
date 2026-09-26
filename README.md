# Alfred-OS

Voice-controlled macOS agent. This repo holds the **Orchestration Engine** (`orchestrator/`) and the **Browser Agent** (`browser_agent/`).

```bash
cd /path/to/Alfred-OS
source .venv/bin/activate
uv sync                                   # creates .venv and installs deps
cp .env.example .env                      # add TYPESAFE_API_KEY, GEMINI_API_KEY (optional OPENROUTER_API_KEY fallback) (+ optional ANTHROPIC_API_KEY)
npx -y @playwright/mcp@0.0.82 install-browser chrome-for-testing   # once
uv run uvicorn orchestrator.main:app --reload --host 127.0.0.1 --port 8000
python test_cli.py "lower the volume"
uv run pytest -q
```

See [SUMMARY.md](SUMMARY.md) for the overview and [docs/EXTENDING.md](docs/EXTENDING.md) to plug in agents.

The **desktop** route uses the Haiku tool agent in `desktop_use` (filesystem + native tools). Set
`ANTHROPIC_API_KEY` in `.env`. Optional: `DESKTOP_FS_ALLOWED_DIRS` (colon-separated paths). You only need
`uvicorn orchestrator.main:app` — no separate desktop-use server unless you want the standalone API on port 8787.
