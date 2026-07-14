"""Tool: list accounts of a budget."""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from ynab_mcp.client import YnabClient
from ynab_mcp.errors import handle_api_error
from ynab_mcp.formatting import ResponseFormat, milliunits_to_amount, to_json
from ynab_mcp.tools._common import READ_ONLY


def register(mcp: FastMCP, client: YnabClient) -> None:
    default_budget = client.default_budget

    @mcp.tool(
        name="ynab_list_accounts",
        annotations={"title": "List accounts", **READ_ONLY},
    )
    async def ynab_list_accounts(
        budget_id: Annotated[
            str, Field(description="Budget id, or 'last-used'")
        ] = default_budget,
        include_closed: Annotated[
            bool, Field(description="Include closed accounts")
        ] = False,
        response_format: ResponseFormat = ResponseFormat.MARKDOWN,
    ) -> str:
        """List a budget's accounts with their balance (converted to currency units).

        Returns: id, name, type, on_budget (bool), current balance, closed flag.
        """
        try:
            data = await client.request("GET", f"/budgets/{budget_id}/accounts")
            accounts = []
            for a in data.get("accounts", []):
                if a.get("closed") and not include_closed:
                    continue
                accounts.append(
                    {
                        "id": a["id"],
                        "name": a["name"],
                        "type": a.get("type"),
                        "on_budget": a.get("on_budget"),
                        "balance": milliunits_to_amount(a.get("balance")),
                        "closed": a.get("closed"),
                    }
                )
            if response_format is ResponseFormat.JSON:
                return to_json(accounts)
            lines = [f"# Accounts ({budget_id})", ""]
            for a in accounts:
                lines.append(
                    f"- **{a['name']}** ({a['type']}): {a['balance']} — id `{a['id']}`"
                )
            return "\n".join(lines)
        except Exception as e:  # noqa: BLE001
            return handle_api_error(e)
