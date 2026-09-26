# Alfred voice input (Electron)

Tap **⌥Space**, speak, and tap **⌥Space** again. The overlay then:
- transcribes what you said (Deepgram India endpoint by default, or OpenAI);
- sends the text to the orchestrator;
- shows the route, the answer, the steps and the latencies.

Destructive commands ask first: click **Yes, do it** or **No**, or tap ⌥Space and say "yes" or "no". **Esc** cancels a recording.

```bash
# 1. Start the orchestrator (repo root)
uv sync && uv run uvicorn orchestrator.main:app --port 8000

# 2. Start the overlay
cd app && npm install && npm start
```

Configuration lives in the repo-root `.env` (see `.env.example`):

| Setting | What it does |
|---|---|
| `DEEPGRAM_API_KEY` / `OPENAI_API_KEY` | Keys; a provider without a key shows "(no key)" in the tray |
| `DEEPGRAM_BASE_URL` | Default `https://api.in.deepgram.com` (inference in India) |
| `STT_PROVIDER` / `STT_MODEL` / `STT_LANGUAGE` | Defaults; the tray menu ("Alfred" in the menu bar) switches provider and model until restart |
| `ORCHESTRATOR_URL`, `HOTKEY` | Orchestrator address and the global shortcut |

macOS asks for microphone access the first time. In development the permission belongs to "Electron".

`npm test` runs the offline tests. For a demo without a mic, `ALFRED_PREVIEW_WAV=take.wav npm start` runs a recorded file through the real pipeline; `say -o take.wav --data-format=LEI16@16000 "lower the volume"` makes one.
