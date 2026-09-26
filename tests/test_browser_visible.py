from browser_agent.config import ROOT, BrowserSettings, load_mcp_servers


def test_visible_browser_is_a_second_server_without_headless(monkeypatch):
    monkeypatch.setenv("BROWSER_HEADLESS", "true")
    monkeypatch.setenv("BROWSER_VISIBLE", "true")
    servers = {s.name: s for s in load_mcp_servers(ROOT / "mcp_servers.json")}
    assert "--headless" in servers["playwright"].args            # research stays hidden and muted
    assert "--headless" not in servers["playwright_visible"].args  # music and videos get a window and sound


def test_visible_browser_can_be_turned_off(monkeypatch):
    monkeypatch.setenv("BROWSER_VISIBLE", "false")
    assert "playwright_visible" not in {s.name for s in load_mcp_servers(ROOT / "mcp_servers.json")}


def test_unsafe_tools_are_denied_in_both_browsers(monkeypatch):
    monkeypatch.delenv("BROWSER_TOOL_DENYLIST", raising=False)
    deny = BrowserSettings.from_env().tool_denylist
    assert {"playwright__browser_run_code_unsafe", "playwright_visible__browser_run_code_unsafe"} <= deny
