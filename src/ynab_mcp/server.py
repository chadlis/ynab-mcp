"""FastMCP server instance, tool registration, and process entry point.

Transport:
- stdio by default (local use, e.g. Claude Desktop / claude.ai local).
- streamable-http when MCP_TRANSPORT=http (remote hosting, endpoint /mcp).

Uses the `fastmcp` package (not `mcp.server.fastmcp`) so this module is
directly deployable on FastMCP Cloud via the `ynab_mcp.server:mcp` entrypoint.
"""

from __future__ import annotations

from fastmcp import FastMCP

from ynab_mcp.client import YnabClient
from ynab_mcp.config import Settings
from ynab_mcp.tools import register_all


def build_server(settings: Settings | None = None) -> FastMCP:
    """Create the FastMCP server with every YNAB tool registered."""
    settings = settings or Settings.from_env()
    server = FastMCP("ynab_mcp")
    client = YnabClient(settings)
    register_all(server, client)
    return server


# Default instance, built from the environment at import time. This is what
# `main()` runs locally and what a `module:object` deploy target (e.g.
# FastMCP Cloud's `ynab_mcp.server:mcp`) imports and serves directly.
mcp = build_server()


def main() -> None:
    """Console entry point (see [project.scripts] in pyproject.toml)."""
    settings = Settings.from_env()
    if settings.transport in ("http", "streamable-http", "streamable_http"):
        # Remote hosting: HTTP endpoint at /mcp.
        mcp.run(transport="streamable-http", host=settings.host, port=settings.port)
    else:
        # Local: communicate over stdin/stdout.
        mcp.run()


if __name__ == "__main__":
    main()
