from __future__ import annotations

import asyncio
import fnmatch
import os
import shutil
from pathlib import Path
from typing import Any


class FilesystemError(RuntimeError):
    """Raised when a filesystem tool violates sandbox rules or fails."""


def _allowed_roots() -> list[Path]:
    raw = os.getenv("DESKTOP_FS_ALLOWED_DIRS", "").strip()
    if raw:
        roots = [Path(part).expanduser().resolve() for part in raw.split(os.pathsep) if part.strip()]
    else:
        home = Path.home()
        roots = [
            (home / "Desktop").resolve(),
            (home / "Documents").resolve(),
            (home / "Downloads").resolve(),
        ]
    existing = [root for root in roots if root.exists()]
    return existing or roots


def _resolve_allowed(path_str: str) -> Path:
    if not path_str or not str(path_str).strip():
        raise FilesystemError("path is required")
    target = Path(str(path_str).strip()).expanduser()
    if not target.is_absolute():
        raise FilesystemError("path must be absolute")
    resolved = target.resolve()
    roots = _allowed_roots()
    for root in roots:
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            continue
    allowed = ", ".join(str(r) for r in roots)
    raise FilesystemError(f"Path {resolved} is outside allowed directories: {allowed}")


async def read_file(path: str, max_bytes: int = 512_000) -> dict[str, Any]:
    """Read a text file within allowed directories."""
    resolved = _resolve_allowed(path)
    if not resolved.is_file():
        raise FilesystemError(f"Not a file: {resolved}")

    def _read() -> dict[str, Any]:
        size = resolved.stat().st_size
        if size > max_bytes:
            raise FilesystemError(f"File too large ({size} bytes); max {max_bytes}")
        text = resolved.read_text(encoding="utf-8", errors="replace")
        return {"path": str(resolved), "size": size, "content": text}

    return await asyncio.to_thread(_read)


async def write_file(path: str, content: str, append: bool = False) -> dict[str, Any]:
    """Write or append UTF-8 text to a file within allowed directories."""
    resolved = _resolve_allowed(path)

    def _write() -> dict[str, Any]:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with resolved.open(mode, encoding="utf-8") as handle:
            handle.write(content)
        return {"path": str(resolved), "bytes_written": len(content.encode("utf-8")), "append": append}

    return await asyncio.to_thread(_write)


async def list_directory(path: str, limit: int = 100) -> dict[str, Any]:
    """List entries in a directory within allowed directories."""
    resolved = _resolve_allowed(path)
    if not resolved.is_dir():
        raise FilesystemError(f"Not a directory: {resolved}")
    cap = min(max(limit, 1), 500)

    def _list() -> dict[str, Any]:
        entries = sorted(resolved.iterdir(), key=lambda item: item.name.casefold())[:cap]
        return {
            "path": str(resolved),
            "entries": [
                {
                    "name": entry.name,
                    "type": "directory" if entry.is_dir() else "file",
                    "size": entry.stat().st_size if entry.is_file() else None,
                }
                for entry in entries
            ],
        }

    return await asyncio.to_thread(_list)


async def search_files(path: str, pattern: str, max_results: int = 50) -> dict[str, Any]:
    """Glob-style search (e.g. *.pdf) under an allowed directory tree."""
    root = _resolve_allowed(path)
    if not root.is_dir():
        raise FilesystemError(f"Not a directory: {root}")
    cap = min(max(max_results, 1), 200)

    def _search() -> dict[str, Any]:
        matches: list[str] = []
        for dirpath, _, filenames in os.walk(root):
            current = Path(dirpath)
            for name in filenames:
                if fnmatch.fnmatch(name.casefold(), pattern.casefold()):
                    matches.append(str((current / name).resolve()))
                    if len(matches) >= cap:
                        return {"root": str(root), "pattern": pattern, "matches": matches}
        return {"root": str(root), "pattern": pattern, "matches": matches}

    return await asyncio.to_thread(_search)


async def move_file(source: str, destination: str) -> dict[str, Any]:
    """Move or rename a file within allowed directories."""
    src = _resolve_allowed(source)
    dst = _resolve_allowed(destination)
    if not src.exists():
        raise FilesystemError(f"Source does not exist: {src}")

    def _move() -> dict[str, Any]:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return {"source": str(src), "destination": str(dst), "moved": True}

    return await asyncio.to_thread(_move)


async def delete_file(path: str) -> dict[str, Any]:
    """Delete a file within allowed directories."""
    resolved = _resolve_allowed(path)
    if not resolved.is_file():
        raise FilesystemError(f"Not a file: {resolved}")

    def _delete() -> dict[str, Any]:
        resolved.unlink()
        return {"path": str(resolved), "deleted": True}

    return await asyncio.to_thread(_delete)


async def create_directory(path: str) -> dict[str, Any]:
    """Create a directory (and parents) within allowed directories."""
    resolved = _resolve_allowed(path)

    def _mkdir() -> dict[str, Any]:
        resolved.mkdir(parents=True, exist_ok=True)
        return {"path": str(resolved), "created": True}

    return await asyncio.to_thread(_mkdir)
