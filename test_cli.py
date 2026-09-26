"""Hit the local server end-to-end: `python test_cli.py "lower the volume"`.

Prompts y/n when the engine asks for confirmation. Use --url to point elsewhere, --yes/--no to auto-answer.
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("transcript", nargs="+")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    answer = parser.add_mutually_exclusive_group()
    answer.add_argument("--yes", action="store_true", help="auto-approve confirmation")
    answer.add_argument("--no", action="store_true", help="auto-decline confirmation")
    args = parser.parse_args()

    with httpx.Client(base_url=args.url, timeout=60) as client:
        try:
            resp = client.post("/transcript", json={"transcript": " ".join(args.transcript)})
        except httpx.ConnectError:
            print(f"Cannot reach {args.url}. Start it with: uvicorn orchestrator.main:app --port 8000", file=sys.stderr)
            return 1
        data = resp.json()
        print(json.dumps(data, indent=2))

        if data.get("status") == "needs_confirmation":
            approved = args.yes or (not args.no and input(f"\n{data['response_text']} [y/N] ").strip().lower() in {"y", "yes"})
            data = client.post("/confirm", json={"session_id": data["session_id"], "approved": approved}).json()
            print(json.dumps(data, indent=2))
    return 0 if data.get("status") in {"completed", "cancelled"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
