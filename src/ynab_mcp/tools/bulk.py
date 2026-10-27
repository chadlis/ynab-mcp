"""Tool: update many transactions in a single API call."""

from __future__ import annotations

from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import BaseModel, Field

from ynab_mcp.client import YnabClient
from ynab_mcp.errors import ToolInputError, handle_api_error
from ynab_mcp.formatting import milliunits_to_amount
from ynab_mcp.tools._common import WRITE_UPDATE
from ynab_mcp.tools._txn import FlagColor, check_payee_args, flag_value, resolve_payee

MAX_BATCH = 100


class BulkUpdateItem(BaseModel):
    """Changes for one transaction; omitted fields are left unchanged."""

    id: str = Field(description="Transaction id")
    category_id: str | None = None
    approved: bool | None = None
    memo: str | None = None
    cleared: str | None = Field(default=None, description="'cleared' or 'uncleared'")
    flag_color: FlagColor | None = Field(default=None, description="'none' clears the flag")
    payee_id: str | None = None
    payee_name: str | None = Field(default=None, description="Never 'Transfer : …'")
    transfer_account_id: str | None = None
    transfer_account_name: str | None = Field(
        default=None, description="Transfer target account name (case/emoji ignored)"
    )


def register(mcp: FastMCP, client: YnabClient) -> None:
    default_budget = client.default_budget

    @mcp.tool(
        name="ynab_update_transactions",
        annotations={"title": "Update transactions in bulk", **WRITE_UPDATE},
    )
    async def ynab_update_transactions(
        transactions: Annotated[
            list[BulkUpdateItem],
            Field(description=f"1 to {MAX_BATCH} updates", min_length=1, max_length=MAX_BATCH),
        ],
        budget_id: Annotated[
            str, Field(description="Budget id, or 'last-used'")
        ] = default_budget,
    ) -> str:
        """Categorize / approve / flag / re-memo many transactions in ONE API call.

        Use this instead of repeated ynab_update_transaction calls (the API
        quota is 200 requests/hour). Transfer rules are the same as in
        ynab_update_transaction (an extra read is made only when an item sets
        a transfer). Splits are not supported here: use ynab_split_transaction.
        Returns a per-id success/failure recap and the remaining API quota.

        Example — approve 3 and categorize one:
        {"transactions": [{"id": "t1", "approved": true},
                          {"id": "t2", "approved": true},
                          {"id": "t3", "category_id": "<groceries>", "approved": true}]}
        """
        try:
            failures: dict[str, str] = {}
            transfer_ids: set[str] = set()
            for item in transactions:
                try:
                    if check_payee_args(
                        item.payee_id,
                        item.payee_name,
                        item.transfer_account_id,
                        item.transfer_account_name,
                    ):
                        transfer_ids.add(item.id)
                except ToolInputError as e:
                    failures[item.id] = str(e)

            account_of: dict[str, str] = {}
            if transfer_ids:
                # One read of the whole register beats one GET per transaction.
                data = await client.request("GET", f"/budgets/{budget_id}/transactions")
                account_of = {t["id"]: t["account_id"] for t in data.get("transactions", [])}

            patches: list[dict[str, Any]] = []
            warnings: list[str] = []
            for item in transactions:
                if item.id in failures:
                    continue
                if item.id in transfer_ids and item.id not in account_of:
                    failures[item.id] = "transaction not found."
                    continue
                try:
                    patch, warns = await resolve_payee(
                        client,
                        budget_id,
                        source_account_id=account_of.get(item.id, ""),
                        payee_id=item.payee_id,
                        payee_name=item.payee_name,
                        transfer_account_id=item.transfer_account_id,
                        transfer_account_name=item.transfer_account_name,
                        category_id=item.category_id,
                    )
                except ToolInputError as e:
                    failures[item.id] = str(e)
                    continue
                warnings += [f"{item.id}: {w}" for w in warns]
                for key in ("approved", "memo", "cleared"):
                    value = getattr(item, key)
                    if value is not None:
                        patch[key] = value
                if item.flag_color is not None:
                    patch["flag_color"] = flag_value(item.flag_color)
                if not patch:
                    failures[item.id] = "nothing to update."
                    continue
                patches.append({"id": item.id, **patch})

            updated: dict[str, dict] = {}
            if patches:
                data = await client.request(
                    "PATCH",
                    f"/budgets/{budget_id}/transactions",
                    json_body={"transactions": patches},
                )
                returned = {t["id"]: t for t in data.get("transactions") or []}
                for tid in data.get("transaction_ids") or list(returned):
                    updated[tid] = returned.get(tid, {})
                for p in patches:
                    if p["id"] not in updated:
                        failures[p["id"]] = "not updated by YNAB (unknown id?)."

            lines = [
                f"# Bulk update: {len(updated)} succeeded, {len(failures)} failed "
                f"(1 write call)",
                "",
            ]
            for tid, t in updated.items():
                detail = (
                    f" · {t.get('payee_name') or '?'} · {milliunits_to_amount(t.get('amount'))} "
                    f"· [{t.get('category_name') or '—'}] · approved={t.get('approved')}"
                    if t
                    else ""
                )
                lines.append(f"- ✅ `{tid}`{detail}")
            for tid, reason in failures.items():
                lines.append(f"- ❌ `{tid}`: {reason}")
            lines += [f"⚠️ {w}" for w in warnings]
            lines += ["", client.rate_limit_status()]
            return "\n".join(lines)
        except Exception as e:  # noqa: BLE001
            return f"{handle_api_error(e)}\n{client.rate_limit_status()}"
