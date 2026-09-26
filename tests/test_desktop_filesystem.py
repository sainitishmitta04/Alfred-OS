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
