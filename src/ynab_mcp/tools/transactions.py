"""Tools: list, create, and update transactions."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import BaseModel, Field

from ynab_mcp.client import YnabClient
from ynab_mcp.errors import handle_api_error
from ynab_mcp.formatting import (
    ResponseFormat,
    amount_to_milliunits,
    milliunits_to_amount,
    paginate,
    to_json,
)
from ynab_mcp.tools._common import READ_ONLY, WRITE_CREATE, WRITE_UPDATE


class SplitItem(BaseModel):
    """One split line of a multi-category transaction."""

    amount: float = Field(
        description="Split amount in currency units, same sign convention as the "
        "parent amount. All splits must sum to the parent amount."
    )
    category_id: str = Field(description="Category for this split")
    memo: str | None = Field(default=None, description="Memo for this split line")


def register(mcp: FastMCP, client: YnabClient) -> None:
    default_budget = client.default_budget

    @mcp.tool(
        name="ynab_list_transactions",
        annotations={"title": "List transactions", **READ_ONLY},
    )
    async def ynab_list_transactions(
        budget_id: Annotated[
            str, Field(description="Budget id, or 'last-used'")
        ] = default_budget,
        account_id: Annotated[
            str | None, Field(description="Filter by account")
        ] = None,
        category_id: Annotated[
            str | None, Field(description="Filter by category")
        ] = None,
        since_date: Annotated[
            str | None, Field(description="Only since this date, format YYYY-MM-DD")
        ] = None,
        txn_type: Annotated[
            str | None,
            Field(description="'uncategorized' or 'unapproved' to return only those"),
        ] = None,
        limit: Annotated[int, Field(description="Max results", ge=1, le=100)] = 25,
        offset: Annotated[int, Field(description="Pagination offset", ge=0)] = 0,
        response_format: ResponseFormat = ResponseFormat.MARKDOWN,
    ) -> str:
        """List a budget's transactions, with filters and pagination.

        Filter by account OR by category (not both, per the API), by date
        (since_date) and by type (uncategorized / unapproved). Amount is in
        currency units (negative = expense). Returns id, date, payee_name, amount,
        category_name, memo, approved, cleared.
        """
        try:
            # Pick the specialized endpoint based on the primary filter.
            if account_id:
                path = f"/budgets/{budget_id}/accounts/{account_id}/transactions"
            elif category_id:
                path = f"/budgets/{budget_id}/categories/{category_id}/transactions"
            else:
                path = f"/budgets/{budget_id}/transactions"

            params: dict[str, Any] = {}
            if since_date:
                params["since_date"] = since_date
            if txn_type:
                params["type"] = txn_type

            data = await client.request("GET", path, params=params or None)
            txns = [
                {
                    "id": t["id"],
                    "date": t.get("date"),
                    "payee_name": t.get("payee_name"),
                    "amount": milliunits_to_amount(t.get("amount")),
                    "category_name": t.get("category_name"),
                    "memo": t.get("memo"),
                    "approved": t.get("approved"),
                    "cleared": t.get("cleared"),
                }
                for t in data.get("transactions", [])
                if not t.get("deleted")
            ]
            txns.sort(key=lambda x: x["date"] or "", reverse=True)
            page = paginate(txns, limit, offset)
            if response_format is ResponseFormat.JSON:
                return to_json(page)
            lines = [f"# Transactions ({page['count']}/{page['total']})", ""]
            for t in page["items"]:
                cat = t["category_name"] or "—"
                flag = "" if t["approved"] else " ⚠️unapproved"
                lines.append(
                    f"- {t['date']} · **{t['payee_name'] or '?'}** · {t['amount']} "
                    f"· [{cat}]{flag} — id `{t['id']}`"
                )
            if page["has_more"]:
                remaining = page["total"] - offset - page["count"]
                lines.append(f"\n_… {remaining} more (next offset: {page['next_offset']})_")
            return "\n".join(lines)
        except Exception as e:  # noqa: BLE001
            return handle_api_error(e)

    @mcp.tool(
        name="ynab_create_transaction",
        annotations={"title": "Create a transaction", **WRITE_CREATE},
    )
    async def ynab_create_transaction(
        account_id: Annotated[str, Field(description="Target account (required)")],
        amount: Annotated[
            float,
            Field(
                description="Amount in currency units. NEGATIVE for an expense, "
                "positive for income. E.g. -12.50"
            ),
        ],
        budget_id: Annotated[
            str, Field(description="Budget id, or 'last-used'")
        ] = default_budget,
        txn_date: Annotated[
            str | None, Field(description="Date YYYY-MM-DD (default: today)")
        ] = None,
        payee_name: Annotated[
            str | None, Field(description="Payee name (created if it does not exist)")
        ] = None,
        category_id: Annotated[
            str | None,
            Field(description="Category to assign (omit when using subtransactions)"),
        ] = None,
        memo: Annotated[str | None, Field(description="Free-form memo")] = None,
        cleared: Annotated[
            str, Field(description="'cleared', 'uncleared' or 'reconciled'")
        ] = "uncleared",
        approved: Annotated[bool, Field(description="Mark as approved")] = True,
        subtransactions: Annotated[
            list[SplitItem] | None,
            Field(
                description="Optional splits across multiple categories. When "
                "provided, their amounts must sum to `amount`, and `category_id` "
                "is ignored (YNAB categorizes each split individually)."
            ),
        ] = None,
    ) -> str:
        """Create a transaction in an account.

        The amount is given in normal currency units (e.g. -12.50 for a 12.50
        expense); conversion to milliunits is automatic. Returns the new id.

        For a transaction split across multiple categories (e.g. one grocery
        receipt covering both "Groceries" and "Household Supplies"), pass
        subtransactions instead of category_id.
        """
        try:
            if subtransactions:
                split_total = round(sum(s.amount for s in subtransactions), 2)
                if round(amount, 2) != split_total:
                    return (
                        f"Error: subtransactions must sum to `amount`. "
                        f"Got {split_total} across {len(subtransactions)} splits vs "
                        f"amount={amount}."
                    )

            transaction: dict[str, Any] = {
                "account_id": account_id,
                "date": txn_date or date.today().isoformat(),
                "amount": amount_to_milliunits(amount),
                "cleared": cleared,
                "approved": approved,
            }
            if payee_name:
                transaction["payee_name"] = payee_name
            if memo:
                transaction["memo"] = memo
            if subtransactions:
                transaction["subtransactions"] = [
                    {
                        "amount": amount_to_milliunits(s.amount),
                        "category_id": s.category_id,
                        **({"memo": s.memo} if s.memo else {}),
                    }
                    for s in subtransactions
                ]
            elif category_id:
                transaction["category_id"] = category_id

            data = await client.request(
                "POST",
                f"/budgets/{budget_id}/transactions",
                json_body={"transaction": transaction},
            )
            t = data.get("transaction", {})
            split_note = f" ({len(subtransactions)} splits)" if subtransactions else ""
            return (
                f"✅ Transaction created: id `{t.get('id')}` · {t.get('date')} · "
                f"{milliunits_to_amount(t.get('amount'))} · {t.get('payee_name') or '?'}"
                f"{split_note}"
            )
        except Exception as e:  # noqa: BLE001
            return handle_api_error(e)

    @mcp.tool(
        name="ynab_update_transaction",
        annotations={"title": "Update a transaction", **WRITE_UPDATE},
    )
    async def ynab_update_transaction(
        transaction_id: Annotated[str, Field(description="Id of the transaction to edit")],
        budget_id: Annotated[
            str, Field(description="Budget id, or 'last-used'")
        ] = default_budget,
        category_id: Annotated[str | None, Field(description="New category")] = None,
        payee_name: Annotated[str | None, Field(description="New payee")] = None,
        memo: Annotated[str | None, Field(description="New memo")] = None,
        amount: Annotated[
            float | None,
            Field(description="New amount in currency units (negative = expense)"),
        ] = None,
        approved: Annotated[
            bool | None, Field(description="Approve / unapprove")
        ] = None,
        cleared: Annotated[
            str | None, Field(description="'cleared', 'uncleared' or 'reconciled'")
        ] = None,
    ) -> str:
        """Partially update a transaction (categorize, approve, fix a memo…).

        Only the provided fields change. Typical case: assign category_id +
        approved=true to an imported, uncategorized transaction.
        """
        try:
            patch: dict[str, Any] = {}
            if category_id is not None:
                patch["category_id"] = category_id
            if payee_name is not None:
                patch["payee_name"] = payee_name
            if memo is not None:
                patch["memo"] = memo
            if amount is not None:
                patch["amount"] = amount_to_milliunits(amount)
            if approved is not None:
                patch["approved"] = approved
            if cleared is not None:
                patch["cleared"] = cleared

            if not patch:
                return "Nothing to update: provide at least one field."

            data = await client.request(
                "PATCH",
                f"/budgets/{budget_id}/transactions/{transaction_id}",
                json_body={"transaction": patch},
            )
            t = data.get("transaction", {})
            return (
                f"✅ Transaction updated: id `{t.get('id')}` · "
                f"category {t.get('category_name') or '—'} · "
                f"approved={t.get('approved')}"
            )
        except Exception as e:  # noqa: BLE001
            return handle_api_error(e)
