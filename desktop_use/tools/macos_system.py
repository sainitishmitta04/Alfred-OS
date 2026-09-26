from __future__ import annotations

import asyncio
import platform
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from desktop_use.tools.system_utils import SystemUtilsError, _run_command


def _require_darwin() -> None:
    if platform.system() != "Darwin":
        raise SystemUtilsError("This tool is supported on macOS only.")


def _run_osascript(script: str) -> str:
    return _run_command(["osascript", "-e", script])


async def control_volume(action: str, level: int | None = None, steps: int = 5) -> dict[str, Any]:
    """Get, set, nudge, mute, or unmute system output volume (macOS)."""
    _require_darwin()
    normalized = action.strip().casefold()
    allowed = {"get", "set", "up", "down", "mute", "unmute"}
    if normalized not in allowed:
        raise SystemUtilsError(f"Unsupported volume action: {action!r}. Use {sorted(allowed)}.")

    if normalized == "get":
        script = "output volume of (get volume settings)"
        value = await asyncio.to_thread(_run_osascript, script)
        return {"action": normalized, "level": int(value.strip())}

    if normalized == "set":
        if level is None:
            raise SystemUtilsError("level is required for set (0-100).")
        if not 0 <= level <= 100:
            raise SystemUtilsError("level must be between 0 and 100.")
        script = f"set volume output volume {level}"
        await asyncio.to_thread(_run_osascript, script)
        return {"action": normalized, "level": level}

    if normalized == "up":
        delta = max(1, min(steps, 25))
        script = f"set volume output volume ((output volume of (get volume settings)) + {delta})"
        await asyncio.to_thread(_run_osascript, script)
        return {"action": normalized, "steps": delta}

    if normalized == "down":
        delta = max(1, min(steps, 25))
        script = f"set volume output volume ((output volume of (get volume settings)) - {delta})"
        await asyncio.to_thread(_run_osascript, script)
        return {"action": normalized, "steps": delta}

    if normalized == "mute":
        await asyncio.to_thread(_run_osascript, "set volume with output muted")
        return {"action": normalized, "muted": True}

    await asyncio.to_thread(_run_osascript, "set volume without output muted")
    return {"action": normalized, "muted": False}


async def lock_screen() -> dict[str, Any]:
    """Lock the macOS session (Ctrl+Cmd+Q shortcut via System Events)."""
    _require_darwin()
    script = 'tell application "System Events" to keystroke "q" using {command down, control down}'
    await asyncio.to_thread(_run_osascript, script)
    return {"locked": True, "message": "Screen lock requested."}


async def capture_screenshot(path: str | None = None) -> dict[str, Any]:
    """Capture the main display to PNG (default: ~/Desktop)."""
    _require_darwin()
    target = Path(path).expanduser() if path else Path.home() / "Desktop" / f"alfred-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.png"
    if not target.is_absolute():
        target = target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(_run_command, ["screencapture", "-x", str(target)])
    return {"path": str(target), "captured": True}


async def set_appearance(mode: str) -> dict[str, Any]:
    """Switch macOS appearance to dark, light, or toggle."""
    _require_darwin()
    normalized = mode.strip().casefold()
    if normalized not in {"dark", "light", "toggle"}:
        raise SystemUtilsError("mode must be dark, light, or toggle.")
    if normalized == "toggle":
        script = '''
tell application "System Events"
  tell appearance preferences
    set dark mode to not dark mode
    return dark mode
  end tell
end tell
'''
    elif normalized == "dark":
        script = 'tell application "System Events" to tell appearance preferences to set dark mode to true'
    else:
        script = 'tell application "System Events" to tell appearance preferences to set dark mode to false'
    output = await asyncio.to_thread(_run_osascript, script)
    return {"mode": normalized, "dark_mode": output.strip() if output else normalized}


async def open_application(name: str, activate: bool = False) -> dict[str, Any]:
    """Launch or activate a macOS application by name."""
    _require_darwin()
    app_name = name.strip().replace('"', '\\"')
    if not app_name:
        raise SystemUtilsError("Application name is required.")
    script = f'tell application "{app_name}" to launch'
    if activate:
        script += f'\ntell application "{app_name}" to activate'
    await asyncio.to_thread(_run_osascript, script)
    return {"application": app_name, "activate": activate, "launched": True}


async def show_notification(title: str, message: str) -> dict[str, Any]:
    """Display a macOS notification banner."""
    _require_darwin()
    safe_title = title.replace('"', '\\"')
    safe_message = message.replace('"', '\\"')
    script = f'display notification "{safe_message}" with title "{safe_title}"'
    await asyncio.to_thread(_run_osascript, script)
    return {"title": title, "message": message, "shown": True}


async def get_system_info() -> dict[str, Any]:
    """Frontmost app, host name, and macOS version."""
    _require_darwin()
    frontmost = await asyncio.to_thread(
        _run_osascript,
        'tell application "System Events" to get name of first application process whose frontmost is true',
    )
    hostname = await asyncio.to_thread(_run_command, ["scutil", "--get", "LocalHostName"])
    version = platform.mac_ver()[0]
    return {
        "frontmost_application": frontmost.strip(),
        "hostname": hostname.strip(),
        "macos_version": version,
    }
