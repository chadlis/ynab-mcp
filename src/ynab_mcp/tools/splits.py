"""Tool: split an existing (e.g. bank-imported) transaction."""

from __future__ import annotations

from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from ynab_mcp.client import YnabClient
from ynab_mcp.errors import ToolInputError, handle_api_error
from ynab_mcp.formatting import milliunits_to_amount
from ynab_mcp.tools._common import WRITE_UPDATE
from ynab_mcp.tools._txn import SplitItem, build_subtransactions, is_split, txn_line, txn_to_dict


def register(mcp: FastMCP, client: YnabClient) -> None:
    default_budget = client.default_budget

    @mcp.tool(
        name="ynab_split_transaction",
        annotations={"title": "Split an existing transaction", **WRITE_UPDATE},
    )
    async def ynab_split_transaction(
        transaction_id: Annotated[str, Field(description="Id of the transaction to split")],
        subtransactions: Annotated[
            list[SplitItem],
            Field(
                description="At least 2 lines whose amounts sum EXACTLY to the transaction "
                "amount (same sign: negative for an expense). Each line takes a "
                "category_id, and/or a transfer (transfer_account_name / "
                "transfer_account_id), or a payee."
            ),
        ],
        memo: Annotated[str | None, Field(description="New memo for the parent")] = None,
        approved: Annotated[bool | None, Field(description="Approve / unapprove")] = None,
        budget_id: Annotated[
            str, Field(description="Budget id, or 'last-used'")
        ] = default_budget,
    ) -> str:
        """Turn an existing, not-yet-split transaction into a split, in place.

        The transaction keeps its id, import_id (link to the bank import, so
        no duplicate at the next import), date, account and cleared state.
        Refused if it is already split (the YNAB API cannot edit existing
        split lines), reconciled, or a transfer. The sum is checked before any
        write. A line that is a transfer to an off-budget (tracking) account
        needs a category_id; a transfer line to an on-budget account takes none.

        Example (Amazon -63.21 imported on Revolut):
        {"transaction_id": "<id>", "approved": true, "subtransactions": [
          {"amount": -55.55, "category_id": "<🧴 household supplies>"},
          {"amount": -7.66, "transfer_account_name": "imane (non réccurent)",
           "category_id": "<♻️ imane (non réccurent)>", "memo": "her part"}]}
        """
        try:
            current = await client.request(
                "GET", f"/budgets/{budget_id}/transactions/{transaction_id}"
            )
            t = current.get("transaction", {})
            if is_split(t):
                raise ToolInputError(
                    "this transaction is already split; the YNAB API does not support "
                    "editing existing split lines. Edit it in the YNAB app."
                )
            if t.get("cleared") == "reconciled":
                raise ToolInputError("this transaction is reconciled; refusing to split it.")
            if t.get("transfer_account_id"):
                raise ToolInputError(
                    "this transaction is a transfer; remove the transfer before splitting."
                )
            subs, warnings = await build_subtransactions(
                client,
                budget_id,
                source_account_id=t["account_id"],
                parent_milliunits=t["amount"],
                items=subtransactions,
            )
            body: dict[str, Any] = {
                # Unchanged identity fields, sent explicitly so the PUT cannot
                # reset them; category_id must be null for a split parent.
                "account_id": t["account_id"],
                "date": t["date"],
                "amount": t["amount"],
                "category_id": None,
                "subtransactions": subs,
            }
            if t.get("payee_id"):
                body["payee_id"] = t["payee_id"]
            if memo is not None:
                body["memo"] = memo
            if approved is not None:
                body["approved"] = approved

            data = await client.request(
                "PUT",
                f"/budgets/{budget_id}/transactions/{transaction_id}",
                json_body={"transaction": body},
            )
            updated = data.get("transaction", {})
            if not is_split(updated):
                return (
                    "Error: YNAB accepted the request but the transaction is not split "
                    f"(category now {updated.get('category_name') or '—'}; it was "
                    f"{t.get('category_name') or '—'}, category_id `{t.get('category_id')}`). "
                    "Restore the category with ynab_update_transaction if needed, and split "
                    "it in the YNAB app."
                )
            notes = list(warnings)
            if updated.get("import_id") != t.get("import_id"):
                notes.append(
                    f"import_id changed ({t.get('import_id')} -> {updated.get('import_id')})."
                )
            out = [
                f"✅ Transaction split into {len(subs)} lines "
                f"(total {milliunits_to_amount(t['amount'])}, cleared={updated.get('cleared')}, "
                f"import_id kept={updated.get('import_id') == t.get('import_id')}):",
                txn_line(txn_to_dict(updated)),
            ]
            out += [f"⚠️ {n}" for n in notes]
            return "\n".join(out)
        except Exception as e:  # noqa: BLE001
            return handle_api_error(e)
