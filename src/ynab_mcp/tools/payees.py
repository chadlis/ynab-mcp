"""Tool: list payees of a budget."""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from ynab_mcp.client import YnabClient
from ynab_mcp.errors import handle_api_error
from ynab_mcp.formatting import ResponseFormat, paginate, to_json
from ynab_mcp.tools._common import READ_ONLY


def register(mcp: FastMCP, client: YnabClient) -> None:
    default_budget = client.default_budget

    @mcp.tool(
        name="ynab_list_payees",
        annotations={"title": "List payees", **READ_ONLY},
    )
    async def ynab_list_payees(
        budget_id: Annotated[
            str, Field(description="Budget id, or 'last-used'")
        ] = default_budget,
        limit: Annotated[int, Field(description="Max results", ge=1, le=200)] = 50,
        offset: Annotated[int, Field(description="Pagination offset", ge=0)] = 0,
        response_format: ResponseFormat = ResponseFormat.MARKDOWN,
    ) -> str:
        """List a budget's payees, paginated.

        Returns id + name. Useful to find the id of a recurring merchant.
        """
        try:
            data = await client.request("GET", f"/budgets/{budget_id}/payees")
            payees = [
                {"id": p["id"], "name": p["name"]}
                for p in data.get("payees", [])
                if not p.get("deleted")
            ]
            page = paginate(payees, limit, offset)
            if response_format is ResponseFormat.JSON:
                return to_json(page)
            lines = [f"# Payees ({page['count']}/{page['total']})", ""]
            for p in page["items"]:
                lines.append(f"- {p['name']} — id `{p['id']}`")
            if page["has_more"]:
                remaining = page["total"] - offset - page["count"]
                lines.append(f"\n_… {remaining} more (next offset: {page['next_offset']})_")
            return "\n".join(lines)
        except Exception as e:  # noqa: BLE001
            return handle_api_error(e)
