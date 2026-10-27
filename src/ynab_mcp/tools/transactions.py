"""Tools: list, get, create, update, and delete transactions."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from ynab_mcp.client import YnabClient
from ynab_mcp.errors import ToolInputError, handle_api_error
from ynab_mcp.formatting import (
    ResponseFormat,
    amount_to_milliunits,
    milliunits_to_amount,
    paginate,
    to_json,
)
from ynab_mcp.tools._common import DESTRUCTIVE, READ_ONLY, WRITE_CREATE, WRITE_UPDATE
from ynab_mcp.tools._txn import (
    FlagColor,
    SplitItem,
    build_subtransactions,
    check_payee_args,
    flag_value,
    normalize_name,
    resolve_payee,
    txn_line,
    txn_to_dict,
)


def _warnings_text(warnings: list[str]) -> str:
    return "".join(f"\n⚠️ {w}" for w in warnings)


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
        until_date: Annotated[
            str | None, Field(description="Only up to this date (inclusive), YYYY-MM-DD")
        ] = None,
        txn_type: Annotated[
            str | None,
            Field(description="'uncategorized' or 'unapproved' to return only those"),
        ] = None,
        payee_contains: Annotated[
            str | None,
            Field(description="Keep payees containing this text (case/accents ignored)"),
        ] = None,
        amount: Annotated[
            float | None,
            Field(description="Keep only this exact amount (to the cent, sign matters)"),
        ] = None,
        account_name: Annotated[
            str | None,
            Field(description="Keep accounts whose name contains this (case/emoji ignored)"),
        ] = None,
        include_subtransactions: Annotated[
            bool, Field(description="Include the lines of split transactions")
        ] = False,
        limit: Annotated[int, Field(description="Max results", ge=1, le=100)] = 25,
        offset: Annotated[int, Field(description="Pagination offset", ge=0)] = 0,
        response_format: ResponseFormat = ResponseFormat.MARKDOWN,
    ) -> str:
        """List a budget's transactions, with filters and pagination.

        Server-side filters: account OR category (not both, per the API),
        since_date, type (uncategorized / unapproved). Client-side filters (no
        extra API call): until_date, payee_contains, amount, account_name.
        Amount is in currency units (negative = expense).

        Each row: id, date, amount, account_id/account_name, payee, category,
        memo, approved, cleared, flag_color, import_id/imported (true = came
        from the bank feed), transfer_account_id (set when it is a transfer).
        A split shows category_name "Split"; pass include_subtransactions=true
        to see its lines (or use ynab_get_transaction).
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
            payee_needle = normalize_name(payee_contains) if payee_contains else None
            account_needle = normalize_name(account_name) if account_name else None
            amount_cents = round(amount * 100) if amount is not None else None
            txns = []
            for t in data.get("transactions", []):
                if t.get("deleted"):
                    continue
                if until_date and (t.get("date") or "") > until_date:
                    continue
                if payee_needle and payee_needle not in normalize_name(t.get("payee_name") or ""):
                    continue
                if account_needle and account_needle not in normalize_name(
                    t.get("account_name") or ""
                ):
                    continue
                if amount_cents is not None and round((t.get("amount") or 0) / 10) != amount_cents:
                    continue
                row = txn_to_dict(t, include_subtransactions=include_subtransactions)
                for key in ("payee_id", "category_id", "matched_transaction_id"):
                    row.pop(key)
                txns.append(row)
            txns.sort(key=lambda x: x["date"] or "", reverse=True)
            page = paginate(txns, limit, offset)
            if response_format is ResponseFormat.JSON:
                return to_json(page)
            lines = [f"# Transactions ({page['count']}/{page['total']})", ""]
            lines.extend(txn_line(t) for t in page["items"])
            if page["has_more"]:
                remaining = page["total"] - offset - page["count"]
                lines.append(f"\n_… {remaining} more (next offset: {page['next_offset']})_")
            return "\n".join(lines)
        except Exception as e:  # noqa: BLE001
            return handle_api_error(e)

    @mcp.tool(
        name="ynab_get_transaction",
        annotations={"title": "Get a transaction", **READ_ONLY},
    )
    async def ynab_get_transaction(
        transaction_id: Annotated[str, Field(description="Transaction id")],
        budget_id: Annotated[
            str, Field(description="Budget id, or 'last-used'")
        ] = default_budget,
        response_format: ResponseFormat = ResponseFormat.MARKDOWN,
    ) -> str:
        """Everything about one transaction, including the lines of a split.

        Returns account, payee, category (ids and names), memo, cleared,
        approved, flag_color, import_id, matched_transaction_id,
        transfer_account_id and subtransactions[] (amount, category, memo,
        payee / transfer_account_id).
        """
        try:
            data = await client.request(
                "GET", f"/budgets/{budget_id}/transactions/{transaction_id}"
            )
            t = txn_to_dict(data.get("transaction", {}))
            if response_format is ResponseFormat.JSON:
                return to_json(t)
            lines = [f"# Transaction `{t['id']}`", ""]
            for key, value in t.items():
                if key not in ("id", "subtransactions"):
                    lines.append(f"- {key}: {value}")
            if t["subtransactions"]:
                lines += ["", f"## Splits ({len(t['subtransactions'])})"]
                for s in t["subtransactions"]:
                    target = (
                        f" · transfer → `{s['transfer_account_id']}` ({s['payee_name']})"
                        if s["transfer_account_id"]
                        else f" · payee {s['payee_name'] or '—'}"
                    )
                    memo = f" · memo {s['memo']}" if s["memo"] else ""
                    lines.append(
                        f"- {s['amount']} · [{s['category_name'] or '—'}] "
                        f"(category_id `{s['category_id']}`){target}{memo}"
                    )
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
            str | None,
            Field(description="Payee name (created if it does not exist). Never 'Transfer : …'"),
        ] = None,
        payee_id: Annotated[str | None, Field(description="Existing payee id")] = None,
        transfer_account_id: Annotated[
            str | None, Field(description="Make it a transfer to this account (id)")
        ] = None,
        transfer_account_name: Annotated[
            str | None,
            Field(description="Make it a transfer to this account (name, case/emoji ignored)"),
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
        flag_color: Annotated[
            FlagColor | None, Field(description="Flag color ('none' = no flag)")
        ] = None,
        subtransactions: Annotated[
            list[SplitItem] | None,
            Field(
                description="Optional splits across multiple categories and/or transfers. "
                "When provided, their amounts must sum to `amount`, and `category_id` "
                "is ignored (YNAB categorizes each split individually)."
            ),
        ] = None,
    ) -> str:
        """Create a transaction in an account.

        The amount is given in normal currency units (e.g. -12.50 for a 12.50
        expense); conversion to milliunits is automatic. Returns the new id.

        Transfers: never use payee_name="Transfer : X" (YNAB rejects it). Pass
        transfer_account_name="X" (or transfer_account_id). Rules:
        - on-budget -> off-budget (tracking account, e.g. personalLoan,
          otherAsset): category_id is REQUIRED;
        - on-budget -> on-budget: no category (category_id is ignored).
        Example: {"account_id": "<revolut>", "amount": -50,
        "transfer_account_name": "Livret A"}.

        Splits: pass subtransactions instead of category_id, e.g.
        [{"amount": -55.55, "category_id": "<household>"},
         {"amount": -7.66, "transfer_account_name": "imane (non réccurent)",
          "category_id": "<♻️ imane>"}].
        """
        try:
            check_payee_args(payee_id, payee_name, transfer_account_id, transfer_account_name)
            milliunits = amount_to_milliunits(amount)
            transaction: dict[str, Any] = {
                "account_id": account_id,
                "date": txn_date or date.today().isoformat(),
                "amount": milliunits,
                "cleared": cleared,
                "approved": approved,
            }
            warnings: list[str] = []
            if subtransactions:
                subs, warns = await build_subtransactions(
                    client,
                    budget_id,
                    source_account_id=account_id,
                    parent_milliunits=milliunits,
                    items=subtransactions,
                )
                transaction["subtransactions"] = subs
                warnings += warns
                category_id = None
            fields, warns = await resolve_payee(
                client,
                budget_id,
                source_account_id=account_id,
                payee_id=payee_id,
                payee_name=payee_name,
                transfer_account_id=transfer_account_id,
                transfer_account_name=transfer_account_name,
                category_id=category_id,
            )
            warnings += warns
            transaction.update({k: v for k, v in fields.items() if v is not None})
            if memo:
                transaction["memo"] = memo
            if flag_color:
                transaction["flag_color"] = flag_value(flag_color)

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
                f"{split_note}{_warnings_text(warnings)}"
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
        payee_name: Annotated[
            str | None, Field(description="New payee name. Never 'Transfer : …'")
        ] = None,
        payee_id: Annotated[str | None, Field(description="New payee id")] = None,
        transfer_account_id: Annotated[
            str | None, Field(description="Turn it into a transfer to this account (id)")
        ] = None,
        transfer_account_name: Annotated[
            str | None,
            Field(description="Turn it into a transfer to this account (name, case/emoji "
                  "ignored)"),
        ] = None,
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
        flag_color: Annotated[
            FlagColor | None, Field(description="Flag color ('none' clears it)")
        ] = None,
    ) -> str:
        """Partially update a transaction (categorize, approve, fix a memo, make it a transfer…).

        Only the provided fields change. Typical case: assign category_id +
        approved=true to an imported, uncategorized transaction. To split it,
        use ynab_split_transaction; for many transactions at once, use
        ynab_update_transactions (one API call).

        Transfers: pass transfer_account_name (or transfer_account_id), never
        payee_name="Transfer : X". From an on-budget account to an off-budget
        (tracking) account, category_id is REQUIRED; between on-budget accounts
        it is dropped. Example (CPAM refund +38.22 on Revolut, to be tracked in
        the off-budget "mutuelle — avances" account):
        {"transaction_id": "<id>", "transfer_account_name": "mutuelle — avances",
         "category_id": "<♻️ mutuelle — avances>", "approved": true}.
        """
        try:
            is_transfer = check_payee_args(
                payee_id, payee_name, transfer_account_id, transfer_account_name
            )
            source_account_id = ""
            if is_transfer:
                current = await client.request(
                    "GET", f"/budgets/{budget_id}/transactions/{transaction_id}"
                )
                source_account_id = current.get("transaction", {}).get("account_id", "")
            patch, warnings = await resolve_payee(
                client,
                budget_id,
                source_account_id=source_account_id,
                payee_id=payee_id,
                payee_name=payee_name,
                transfer_account_id=transfer_account_id,
                transfer_account_name=transfer_account_name,
                category_id=category_id,
            )
            if memo is not None:
                patch["memo"] = memo
            if amount is not None:
                patch["amount"] = amount_to_milliunits(amount)
            if approved is not None:
                patch["approved"] = approved
            if cleared is not None:
                patch["cleared"] = cleared
            if flag_color is not None:
                patch["flag_color"] = flag_value(flag_color)

            if not patch:
                return "Nothing to update: provide at least one field."

            data = await client.request(
                "PATCH",
                f"/budgets/{budget_id}/transactions/{transaction_id}",
                json_body={"transaction": patch},
            )
            t = data.get("transaction", {})
            transfer = (
                f" · payee {t.get('payee_name')}" if t.get("transfer_account_id") else ""
            )
            return (
                f"✅ Transaction updated: id `{t.get('id')}` · "
                f"category {t.get('category_name') or '—'} · "
                f"approved={t.get('approved')}{transfer}{_warnings_text(warnings)}"
            )
        except Exception as e:  # noqa: BLE001
            return handle_api_error(e)

    @mcp.tool(
        name="ynab_delete_transaction",
        annotations={"title": "Delete a transaction", **DESTRUCTIVE},
    )
    async def ynab_delete_transaction(
        transaction_id: Annotated[str, Field(description="Id of the transaction to delete")],
        confirm: Annotated[
            bool, Field(description="Must be true: deletion cannot be undone via the API")
        ] = False,
        budget_id: Annotated[
            str, Field(description="Budget id, or 'last-used'")
        ] = default_budget,
    ) -> str:
        """Delete a transaction (e.g. a manual duplicate of an imported one).

        Requires confirm=true. Refuses reconciled transactions. Deleting one
        side of a transfer deletes the transfer. Returns the deleted
        transaction's date, payee, amount and account.
        """
        try:
            if not confirm:
                raise ToolInputError("deletion requires confirm=true.")
            current = await client.request(
                "GET", f"/budgets/{budget_id}/transactions/{transaction_id}"
            )
            t = current.get("transaction", {})
            if t.get("cleared") == "reconciled":
                raise ToolInputError("this transaction is reconciled; refusing to delete it.")
            await client.request("DELETE", f"/budgets/{budget_id}/transactions/{transaction_id}")
            return (
                f"🗑️ Transaction deleted: id `{transaction_id}` · {t.get('date')} · "
                f"{t.get('payee_name') or '?'} · {milliunits_to_amount(t.get('amount'))} · "
                f"account {t.get('account_name') or t.get('account_id')}"
            )
        except Exception as e:  # noqa: BLE001
            return handle_api_error(e)
