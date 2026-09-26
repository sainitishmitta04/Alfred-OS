# Alfred-OS

Voice-controlled macOS agent. This repo currently holds the **Orchestration Engine** (`orchestrator/`).

```bash
source .venv/bin/activate
uv sync                                   # install deps
cp .env.example .env                      # add TYPESAFE_API_KEY (+ optional ANTHROPIC_API_KEY)
uvicorn orchestrator.main:app --port 8000
python test_cli.py "lower the volume"
uv run pytest -q
```

See [SUMMARY.md](SUMMARY.md) for the overview and [docs/EXTENDING.md](docs/EXTENDING.md) to plug in agents.
