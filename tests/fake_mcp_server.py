"""Tiny stdio MCP server used by tests."""

from mcp.server.mcpserver import MCPServer

server = MCPServer("fake")


@server.tool()
def echo(text: str) -> str:
    """Echo text back."""
    return f"echo: {text}"


@server.tool()
def add(a: int, b: int) -> str:
    """Add two numbers."""
    return str(a + b)


if __name__ == "__main__":
    server.run("stdio")
