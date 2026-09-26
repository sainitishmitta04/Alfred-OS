from __future__ import annotations

import platform
from unittest.mock import patch

import pytest

from desktop_use.tools.macos_system import control_volume, get_system_info, show_notification
from desktop_use.tools.system_utils import SystemUtilsError


@pytest.mark.skipif(platform.system() != "Darwin", reason="macOS-only")
@pytest.mark.asyncio
async def test_control_volume_get_integration() -> None:
    result = await control_volume("get")
    assert 0 <= result["level"] <= 100


@pytest.mark.asyncio
async def test_control_volume_rejects_invalid_action() -> None:
    with pytest.raises(SystemUtilsError):
        await control_volume("loud")


@pytest.mark.asyncio
async def test_show_notification_calls_osascript() -> None:
    with patch("desktop_use.tools.macos_system._run_osascript", return_value="") as mocked:
        result = await show_notification("Test", "Hello")
    assert result["shown"] is True
    mocked.assert_called_once()


@pytest.mark.asyncio
async def test_get_system_info_mocked() -> None:
    with (
        patch("desktop_use.tools.macos_system._require_darwin"),
        patch("desktop_use.tools.macos_system._run_osascript", return_value="Safari"),
        patch("desktop_use.tools.macos_system._run_command", return_value="my-mac"),
        patch("desktop_use.tools.macos_system.platform.mac_ver", return_value=("15.0", (), "")),
    ):
        result = await get_system_info()
    assert result["frontmost_application"] == "Safari"
    assert result["hostname"] == "my-mac"
