from __future__ import annotations

import asyncio
import platform
import subprocess
from typing import Any


class DesktopControlError(RuntimeError):
    """Raised when a background OS control command fails."""


def _run_osascript(script: str) -> str:
    completed = subprocess.run(
        ["osascript", "-e", script],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        stderr = (completed.stderr or completed.stdout or "osascript failed").strip()
        raise DesktopControlError(stderr)
    return (completed.stdout or "").strip()


async def control_media_player(action: str, track_or_playlist: str | None = None) -> dict[str, Any]:
    """Control Spotify or Apple Music in the background without activating the app window."""
    if platform.system() != "Darwin":
        raise DesktopControlError("Media control is supported on macOS only.")

    normalized = action.strip().casefold()
    allowed = {"play", "pause", "next", "previous", "toggle_play_pause"}
    if normalized not in allowed:
        raise DesktopControlError(f"Unsupported media action: {action!r}. Use one of {sorted(allowed)}.")

    spotify_cmd = {
        "play": "play",
        "pause": "pause",
        "next": "next track",
        "previous": "previous track",
        "toggle_play_pause": "playpause",
    }[normalized]

    spotify_script = f'''
tell application "Spotify"
  if not running then
    launch
    delay 0.3
  end if
  {spotify_cmd}
end tell
'''

    music_script = f'''
tell application "Music"
  if not running then
    launch
    delay 0.3
  end if
  {spotify_cmd.replace("playpause", "playpause")}
end tell
'''

    if track_or_playlist:
        query = track_or_playlist.replace('"', '\\"')
        spotify_script = f'''
tell application "Spotify"
  if not running then launch
  play track "spotify:search:{query}"
end tell
'''
        music_script = f'''
tell application "Music"
  activate
  search playlist "{query}" only playlists
end tell
'''

    last_error: Exception | None = None
    for label, script in (("Spotify", spotify_script), ("Music", music_script)):
        try:
            message = await asyncio.to_thread(_run_osascript, script)
            return {
                "player": label,
                "action": normalized,
                "track_or_playlist": track_or_playlist,
                "message": message or f"{normalized} sent to {label}.",
            }
        except DesktopControlError as error:
            last_error = error
            continue

    raise DesktopControlError(str(last_error) if last_error else "No supported media player responded.")
