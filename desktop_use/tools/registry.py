from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from desktop_use.tools.desktop_control import control_media_player
from desktop_use.tools.filesystem import (
    create_directory,
    delete_file,
    list_directory,
    move_file,
    read_file,
    search_files,
    write_file,
)
from desktop_use.tools.system_utils import execute_system_script
from desktop_use.tools.web_browser import headless_web_scrape

ToolHandler = Callable[..., Awaitable[dict[str, Any]]]

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "read_file",
        "description": "Read a UTF-8 text file from an allowed user directory (Desktop, Documents, Downloads).",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Absolute file path."}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write or append text to a file in allowed directories.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "append": {"type": "boolean"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_directory",
        "description": "List files and folders in an allowed directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "search_files",
        "description": "Find files by glob pattern (e.g. *.txt) under an allowed directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Root directory to search."},
                "pattern": {"type": "string"},
                "max_results": {"type": "integer"},
            },
            "required": ["path", "pattern"],
        },
    },
    {
        "name": "move_file",
        "description": "Move or rename a file within allowed directories.",
        "input_schema": {
            "type": "object",
            "properties": {"source": {"type": "string"}, "destination": {"type": "string"}},
            "required": ["source", "destination"],
        },
    },
    {
        "name": "delete_file",
        "description": "Delete a file within allowed directories.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "create_directory",
        "description": "Create a folder within allowed directories.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "control_media_player",
        "description": "Control Spotify or Apple Music in the background (play, pause, next, previous).",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["play", "pause", "next", "previous", "toggle_play_pause"],
                },
                "track_or_playlist": {"type": "string", "description": "Optional search query."},
            },
            "required": ["action"],
        },
    },
    {
        "name": "headless_web_scrape",
        "description": "Headless browser read or interact with a web page without focus stealing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "action": {
                    "type": "string",
                    "enum": ["extract_text", "extract_html", "fill_input", "click"],
                },
                "selector": {"type": "string"},
                "input_value": {"type": "string"},
            },
            "required": ["url", "action"],
        },
    },
    {
        "name": "execute_system_script",
        "description": "Battery, volume, directory listing, or approved AppleScript utilities.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command_type": {
                    "type": "string",
                    "enum": ["battery_status", "set_volume", "list_project_files", "run_osascript"],
                },
                "args": {"type": "object", "additionalProperties": True},
            },
            "required": ["command_type"],
        },
    },
]

TOOL_HANDLERS: dict[str, ToolHandler] = {
    "read_file": read_file,
    "write_file": write_file,
    "list_directory": list_directory,
    "search_files": search_files,
    "move_file": move_file,
    "delete_file": delete_file,
    "create_directory": create_directory,
    "control_media_player": control_media_player,
    "headless_web_scrape": headless_web_scrape,
    "execute_system_script": execute_system_script,
}
