"""FastMCP server instance, tool registration, and process entry point.

Transport:
- stdio by default (local use, e.g. Claude Desktop / claude.ai local).
- streamable-http when MCP_TRANSPORT=http (remote hosting, endpoint /mcp).
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ynab_mcp.client import YnabClient
from ynab_mcp.config import Settings
from ynab_mcp.tools import register_all


def build_server(settings: Settings | None = None) -> FastMCP:
    """Create the FastMCP server with every YNAB tool registered."""
    settings = settings or Settings.from_env()
    mcp = FastMCP("ynab_mcp", host=settings.host, port=settings.port)
    client = YnabClient(settings)
    register_all(mcp, client)
    return mcp


def main() -> None:
    """Console entry point (see [project.scripts] in pyproject.toml)."""
    settings = Settings.from_env()
    mcp = build_server(settings)
    if settings.transport in ("http", "streamable-http", "streamable_http"):
        # Remote hosting: HTTP endpoint at /mcp.
        mcp.run(transport="streamable-http")
    else:
        # Local: communicate over stdin/stdout.
        mcp.run()


if __name__ == "__main__":
    main()
