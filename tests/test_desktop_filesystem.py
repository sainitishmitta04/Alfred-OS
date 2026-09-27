import os

import pytest

from desktop_use.tools.filesystem import FilesystemError, list_directory, read_file, write_file


@pytest.fixture
def allowed_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("DESKTOP_FS_ALLOWED_DIRS", str(tmp_path))
    return tmp_path


@pytest.mark.asyncio
async def test_write_and_read_file(allowed_tmp):
    target = allowed_tmp / "note.txt"
    await write_file(str(target), "hello alfred")
    result = await read_file(str(target))
    assert result["content"] == "hello alfred"


@pytest.mark.asyncio
async def test_list_directory(allowed_tmp):
    (allowed_tmp / "a.txt").write_text("a", encoding="utf-8")
    result = await list_directory(str(allowed_tmp))
    names = {entry["name"] for entry in result["entries"]}
    assert "a.txt" in names


@pytest.mark.asyncio
async def test_rejects_path_outside_sandbox(allowed_tmp, monkeypatch):
    monkeypatch.setenv("DESKTOP_FS_ALLOWED_DIRS", str(allowed_tmp))
    with pytest.raises(FilesystemError):
        await read_file("/etc/hosts")


async def test_write_file_tolerates_shell_home_paths(tmp_path, monkeypatch):
    """The model sometimes writes $(whoami)/$HOME in paths; the tool should resolve them, not reject them."""
    import getpass

    home = tmp_path
    monkeypatch.setenv("HOME", str(home))
    (home / "Desktop").mkdir()
    monkeypatch.setenv("DESKTOP_FS_ALLOWED_DIRS", str(home / "Desktop"))

    user = getpass.getuser()
    # A shell-style path the way the model emits it; note it uses /Users/<user> which we redirect via HOME parts.
    for raw in (f"$HOME/Desktop/a.md", f"${{HOME}}/Desktop/b.md"):
        result = await write_file(raw, "hi")
        assert "error" not in result, result

    # $(whoami) is expanded to the real username (won't map to tmp_path, so just check it no longer stays literal).
    from desktop_use.tools.filesystem import _expand_home
    assert "$(whoami)" not in _expand_home("/Users/$(whoami)/Desktop/x.md")
    assert user in _expand_home("/Users/$(whoami)/Desktop/x.md")
