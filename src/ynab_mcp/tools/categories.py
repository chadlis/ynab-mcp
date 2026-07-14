"""Tool: list category groups and their categories."""

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
        name="ynab_list_categories",
        annotations={"title": "List categories", **READ_ONLY},
    )
    async def ynab_list_categories(
        budget_id: Annotated[
            str, Field(description="Budget id, or 'last-used'")
        ] = default_budget,
        response_format: ResponseFormat = ResponseFormat.MARKDOWN,
    ) -> str:
        """List category groups and their categories, with budgeted / activity / balance.

        Each category: id, name, budgeted, activity, balance (all in currency units).
        Needed to grab a category_id before creating/categorizing a transaction.
        """
        try:
            data = await client.request("GET", f"/budgets/{budget_id}/categories")
            groups = []
            for g in data.get("category_groups", []):
                if g.get("hidden") or g.get("deleted"):
                    continue
                cats = [
                    {
                        "id": c["id"],
                        "name": c["name"],
                        "budgeted": milliunits_to_amount(c.get("budgeted")),
                        "activity": milliunits_to_amount(c.get("activity")),
                        "balance": milliunits_to_amount(c.get("balance")),
                    }
                    for c in g.get("categories", [])
                    if not c.get("hidden") and not c.get("deleted")
                ]
                groups.append({"group": g["name"], "categories": cats})
            if response_format is ResponseFormat.JSON:
                return to_json(groups)
            lines = [f"# Categories ({budget_id})", ""]
            for g in groups:
                lines.append(f"## {g['group']}")
                for c in g["categories"]:
                    lines.append(f"- {c['name']}: balance {c['balance']} — id `{c['id']}`")
                lines.append("")
            return "\n".join(lines)
        except Exception as e:  # noqa: BLE001
            return handle_api_error(e)
