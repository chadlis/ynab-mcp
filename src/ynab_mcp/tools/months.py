"""Tool: budget month summary."""

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
        name="ynab_get_budget_month",
        annotations={"title": "Month summary", **READ_ONLY},
    )
    async def ynab_get_budget_month(
        budget_id: Annotated[
            str, Field(description="Budget id, or 'last-used'")
        ] = default_budget,
        month: Annotated[
            str, Field(description="'current' or a month as YYYY-MM-01")
        ] = "current",
        response_format: ResponseFormat = ResponseFormat.MARKDOWN,
    ) -> str:
        """Budget summary for a month: to be budgeted, income, budgeted, activity, age of money."""
        try:
            data = await client.request("GET", f"/budgets/{budget_id}/months/{month}")
            m = data.get("month", {})
            summary = {
                "month": m.get("month"),
                "to_be_budgeted": milliunits_to_amount(m.get("to_be_budgeted")),
                "income": milliunits_to_amount(m.get("income")),
                "budgeted": milliunits_to_amount(m.get("budgeted")),
                "activity": milliunits_to_amount(m.get("activity")),
                "age_of_money": m.get("age_of_money"),
            }
            if response_format is ResponseFormat.JSON:
                return to_json(summary)
            return (
                f"# Month {summary['month']}\n\n"
                f"- To be budgeted: **{summary['to_be_budgeted']}**\n"
                f"- Income: {summary['income']}\n"
                f"- Budgeted: {summary['budgeted']}\n"
                f"- Activity: {summary['activity']}\n"
                f"- Age of money: {summary['age_of_money']} days"
            )
        except Exception as e:  # noqa: BLE001
            return handle_api_error(e)
