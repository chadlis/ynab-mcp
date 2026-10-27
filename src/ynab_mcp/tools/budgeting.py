"""Tools: assign money to categories and move money between them."""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from ynab_mcp.client import YnabClient
from ynab_mcp.errors import ToolInputError, handle_api_error
from ynab_mcp.formatting import amount_to_milliunits, milliunits_to_amount
from ynab_mcp.tools._common import WRITE_UPDATE

_MONTH = Field(description="'current' or a month as YYYY-MM-01")


def _category_line(c: dict) -> str:
    return (
        f"**{c.get('name')}**: budgeted {milliunits_to_amount(c.get('budgeted'))} · "
        f"activity {milliunits_to_amount(c.get('activity'))} · "
        f"available {milliunits_to_amount(c.get('balance'))}"
    )


def register(mcp: FastMCP, client: YnabClient) -> None:
    default_budget = client.default_budget

    async def get_category(budget_id: str, month: str, category_id: str) -> dict:
        data = await client.request(
            "GET", f"/budgets/{budget_id}/months/{month}/categories/{category_id}"
        )
        return data.get("category", {})

    async def set_budgeted(budget_id: str, month: str, category_id: str, milliunits: int) -> dict:
        data = await client.request(
            "PATCH",
            f"/budgets/{budget_id}/months/{month}/categories/{category_id}",
            json_body={"category": {"budgeted": milliunits}},
        )
        return data.get("category", {})

    @mcp.tool(
        name="ynab_set_category_budgeted",
        annotations={"title": "Set a category's assigned amount", **WRITE_UPDATE},
    )
    async def ynab_set_category_budgeted(
        category_id: Annotated[str, Field(description="Category id")],
        budgeted: Annotated[
            float, Field(description="New TOTAL assigned amount for the month (not a delta)")
        ],
        month: Annotated[str, _MONTH] = "current",
        budget_id: Annotated[
            str, Field(description="Budget id, or 'last-used'")
        ] = default_budget,
    ) -> str:
        """Set how much is assigned ("budgeted") to a category for a month.

        `budgeted` replaces the current assigned amount. To cover an
        overspent category from another one, prefer ynab_move_money.
        """
        try:
            c = await set_budgeted(budget_id, month, category_id, amount_to_milliunits(budgeted))
            return f"✅ {month}: {_category_line(c)}"
        except Exception as e:  # noqa: BLE001
            return handle_api_error(e)

    @mcp.tool(
        name="ynab_move_money",
        annotations={"title": "Move money between categories", **WRITE_UPDATE},
    )
    async def ynab_move_money(
        from_category_id: Annotated[str, Field(description="Category giving the money")],
        to_category_id: Annotated[str, Field(description="Category receiving the money")],
        amount: Annotated[float, Field(description="Positive amount to move", gt=0)],
        month: Annotated[str, _MONTH] = "current",
        budget_id: Annotated[
            str, Field(description="Budget id, or 'last-used'")
        ] = default_budget,
    ) -> str:
        """Move assigned money from one category to another for a month (e.g. to
        cover an overspending). Reads both categories, then updates both (4 API calls).
        """
        try:
            if from_category_id == to_category_id:
                raise ToolInputError("from and to categories are the same.")
            delta = amount_to_milliunits(amount)
            src = await get_category(budget_id, month, from_category_id)
            dst = await get_category(budget_id, month, to_category_id)
            new_src = await set_budgeted(
                budget_id, month, from_category_id, src["budgeted"] - delta
            )
            try:
                new_dst = await set_budgeted(
                    budget_id, month, to_category_id, dst["budgeted"] + delta
                )
            except Exception as e:  # noqa: BLE001
                return (
                    f"{handle_api_error(e)}\n⚠️ Partial move: {src.get('name')} was already "
                    f"reduced by {amount}. Restore it with ynab_set_category_budgeted("
                    f"category_id={from_category_id!r}, budgeted="
                    f"{milliunits_to_amount(src['budgeted'])}) or retry the second half."
                )
            out = [
                f"✅ Moved {amount} in {month}:",
                f"- from {_category_line(new_src)}",
                f"- to {_category_line(new_dst)}",
            ]
            if (new_src.get("balance") or 0) < 0:
                out.append(f"⚠️ {new_src.get('name')} is now overspent.")
            out.append(client.rate_limit_status())
            return "\n".join(out)
        except Exception as e:  # noqa: BLE001
            return handle_api_error(e)
