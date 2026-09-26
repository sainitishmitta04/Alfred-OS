from __future__ import annotations

import platform

import pytest
from fastapi.testclient import TestClient

from desktop_use.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_list_tools_includes_macos_tools(client: TestClient) -> None:
    names = {item["name"] for item in client.get("/api/v1/tools").json()}
    assert "control_volume" in names
    assert "get_system_info" in names
    assert "execute_system_script" in names


def test_invoke_unknown_tool(client: TestClient) -> None:
    response = client.post("/api/v1/tools/not_a_tool/invoke", json={"arguments": {}})
    assert response.status_code == 404


@pytest.mark.skipif(platform.system() != "Darwin", reason="macOS-only tools")
def test_invoke_battery_status(client: TestClient) -> None:
    response = client.post(
        "/api/v1/tools/execute_system_script/invoke",
        json={"arguments": {"command_type": "battery_status"}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["tool"] == "execute_system_script"
    assert "output" in body["result"] or "command_type" in body["result"]


@pytest.mark.skipif(platform.system() != "Darwin", reason="macOS-only tools")
def test_invoke_control_volume_get(client: TestClient) -> None:
    response = client.post(
        "/api/v1/tools/control_volume/invoke",
        json={"arguments": {"action": "get"}},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["success"] is True
    assert "level" in body["result"]


@pytest.mark.skipif(platform.system() != "Darwin", reason="macOS-only tools")
def test_invoke_get_system_info(client: TestClient) -> None:
    response = client.post("/api/v1/tools/get_system_info/invoke", json={"arguments": {}})
    body = response.json()
    assert body["success"] is True
    assert "frontmost_application" in body["result"]
