# Alfred-OS

Voice-controlled macOS agent. This repo holds the **Orchestration Engine** (`orchestrator/`) and the **Browser Agent** (`browser_agent/`).

```bash
source .venv/bin/activate
uv sync                                   # install deps
cp .env.example .env                      # add TYPESAFE_API_KEY, GEMINI_API_KEY (optional OPENROUTER_API_KEY fallback) (+ optional ANTHROPIC_API_KEY)
npx -y @playwright/mcp@0.0.82 install-browser chrome-for-testing   # once
uvicorn orchestrator.main:app --port 8000
python test_cli.py "lower the volume"
uv run pytest -q
```

See [SUMMARY.md](SUMMARY.md) for the overview and [docs/EXTENDING.md](docs/EXTENDING.md) to plug in agents.
