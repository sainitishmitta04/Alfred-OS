from __future__ import annotations

import asyncio
import platform
import subprocess
from pathlib import Path
from typing import Any


class SystemUtilsError(RuntimeError):
    """Raised when a system utility command fails."""


def _run_command(command: list[str]) -> str:
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        stderr = (completed.stderr or completed.stdout or "command failed").strip()
        raise SystemUtilsError(stderr)
    return (completed.stdout or "").strip()


async def execute_system_script(command_type: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run fast background system actions (volume, battery, directory listing)."""
    args = args or {}
    kind = command_type.strip().casefold()

    if kind == "battery_status":
        if platform.system() != "Darwin":
            output = await asyncio.to_thread(_run_command, ["upower", "-i", "/BAT0"])
            return {"command_type": kind, "output": output}

        output = await asyncio.to_thread(_run_command, ["pmset", "-g", "batt"])
        return {"command_type": kind, "output": output}

    if kind == "set_volume":
        level = int(args.get("level", 50))
        if not 0 <= level <= 100:
            raise SystemUtilsError("Volume level must be between 0 and 100.")
        if platform.system() != "Darwin":
            raise SystemUtilsError("set_volume is supported on macOS only.")
        script = f"set volume output volume {level}"
        await asyncio.to_thread(_run_command, ["osascript", "-e", script])
        return {"command_type": kind, "level": level, "message": f"Output volume set to {level}."}

    if kind == "list_project_files":
        root = Path(str(args.get("path", "."))).expanduser().resolve()
        if not root.exists():
            raise SystemUtilsError(f"Path does not exist: {root}")
        if not root.is_dir():
            raise SystemUtilsError(f"Path is not a directory: {root}")
        limit = min(int(args.get("limit", 50)), 200)
        entries = sorted(root.iterdir(), key=lambda item: item.name.casefold())[:limit]
        files = [
            {"name": entry.name, "type": "directory" if entry.is_dir() else "file"}
            for entry in entries
        ]
        return {"command_type": kind, "path": str(root), "entries": files}

    if kind == "run_osascript":
        if platform.system() != "Darwin":
            raise SystemUtilsError("run_osascript is supported on macOS only.")
        script = str(args.get("script", "")).strip()
        if not script:
            raise SystemUtilsError("args.script is required for run_osascript.")
        output = await asyncio.to_thread(_run_command, ["osascript", "-e", script])
        return {"command_type": kind, "output": output}

    raise SystemUtilsError(
        f"Unsupported command_type: {command_type!r}. "
        "Use battery_status, set_volume, list_project_files, or run_osascript."
    )
