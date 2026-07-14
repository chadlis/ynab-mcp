"""Tool registration: wires every domain module onto the FastMCP server."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ynab_mcp.client import YnabClient
from ynab_mcp.tools import accounts, budgets, categories, months, payees, transactions


def register_all(mcp: FastMCP, client: YnabClient) -> None:
    """Register every YNAB tool on the given server."""
    budgets.register(mcp, client)
    accounts.register(mcp, client)
    categories.register(mcp, client)
    payees.register(mcp, client)
    transactions.register(mcp, client)
    months.register(mcp, client)
