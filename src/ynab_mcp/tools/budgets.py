"""Tool: list YNAB budgets."""

from __future__ import annotations

from fastmcp import FastMCP

from ynab_mcp.client import YnabClient
from ynab_mcp.errors import handle_api_error
from ynab_mcp.formatting import ResponseFormat, to_json
from ynab_mcp.tools._common import READ_ONLY


def register(mcp: FastMCP, client: YnabClient) -> None:
    @mcp.tool(
        name="ynab_list_budgets",
        annotations={"title": "List budgets", **READ_ONLY},
    )
    async def ynab_list_budgets(
        response_format: ResponseFormat = ResponseFormat.MARKDOWN,
    ) -> str:
        """List the YNAB budgets accessible with this token, with their currency.

        Returns for each budget: id, name, currency iso_code, last modified date.
        Useful to grab a specific budget_id (otherwise use "last-used" elsewhere).
        """
        try:
            data = await client.request("GET", "/budgets")
            budgets = [
                {
                    "id": b["id"],
                    "name": b["name"],
                    "currency": (b.get("currency_format") or {}).get("iso_code"),
                    "last_modified_on": b.get("last_modified_on"),
                }
                for b in data.get("budgets", [])
            ]
            if response_format is ResponseFormat.JSON:
                return to_json(budgets)
            lines = ["# YNAB budgets", ""]
            for b in budgets:
                lines.append(f"- **{b['name']}** ({b['currency']}) — id `{b['id']}`")
            return "\n".join(lines)
        except Exception as e:  # noqa: BLE001
            return handle_api_error(e)
