"""Tool registration: wires every domain module onto the FastMCP server."""

from __future__ import annotations

from fastmcp import FastMCP

from ynab_mcp.client import YnabClient
from ynab_mcp.tools import (
    accounts,
    budgeting,
    budgets,
    bulk,
    categories,
    months,
    payees,
    splits,
    transactions,
)


def register_all(mcp: FastMCP, client: YnabClient) -> None:
    """Register every YNAB tool on the given server."""
    budgets.register(mcp, client)
    accounts.register(mcp, client)
    categories.register(mcp, client)
    payees.register(mcp, client)
    transactions.register(mcp, client)
    splits.register(mcp, client)
    bulk.register(mcp, client)
    months.register(mcp, client)
    budgeting.register(mcp, client)
