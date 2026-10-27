"""Shared transaction helpers: payee/transfer resolution, splits, and rendering."""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Literal

from pydantic import BaseModel, Field

from ynab_mcp.client import YnabClient
from ynab_mcp.errors import ToolInputError
from ynab_mcp.formatting import amount_to_milliunits, milliunits_to_amount

FlagColor = Literal["red", "orange", "yellow", "green", "blue", "purple", "none"]

# YNAB rejects payee names starting with one of its internal payee names.
_INTERNAL_PAYEE_RE = re.compile(r"^\s*transfer\s*:", re.IGNORECASE)


class SplitItem(BaseModel):
    """One split line of a multi-category (and/or transfer) transaction."""

    amount: float = Field(
        description="Split amount in currency units, same sign convention as the "
        "parent amount. All splits must sum to the parent amount."
    )
    category_id: str | None = Field(
        default=None,
        description="Category for this line. Required for a transfer to an off-budget "
        "(tracking) account; must be omitted for a transfer between on-budget accounts.",
    )
    memo: str | None = Field(default=None, description="Memo for this split line")
    payee_id: str | None = Field(default=None, description="Payee id for this line")
    payee_name: str | None = Field(
        default=None, description="Payee name for this line (never 'Transfer : …')"
    )
    transfer_account_id: str | None = Field(
        default=None, description="Make this line a transfer to that account (id)"
    )
    transfer_account_name: str | None = Field(
        default=None,
        description="Make this line a transfer to that account (name; case, accents and "
        "emoji are ignored)",
    )


def flag_value(flag_color: FlagColor) -> str | None:
    """'none' clears the flag."""
    return None if flag_color == "none" else flag_color


def normalize_name(name: str) -> str:
    """Casefold and strip accents, emoji and punctuation: '♻️ Mutuelle — Avances' ->
    'mutuelle avances'."""
    decomposed = unicodedata.normalize("NFKD", name)
    kept = [
        ch if unicodedata.category(ch)[0] in "LN" else " "
        for ch in decomposed
        if not unicodedata.combining(ch)
    ]
    return " ".join("".join(kept).casefold().split())


def find_account(
    accounts: list[dict], *, account_id: str | None = None, name: str | None = None
) -> dict:
    """Find an account by exact id, else by normalized name (exact, then unique substring)."""
    if account_id:
        for a in accounts:
            if a["id"] == account_id:
                return a
        raise ToolInputError(f"no account with id {account_id!r}. See ynab_list_accounts.")
    wanted = normalize_name(name or "")
    if not wanted:
        raise ToolInputError("empty account name.")
    open_accounts = [a for a in accounts if not a.get("closed")]
    exact = [a for a in open_accounts if normalize_name(a["name"]) == wanted]
    if len(exact) == 1:
        return exact[0]
    partial = exact or [a for a in open_accounts if wanted in normalize_name(a["name"])]
    if len(partial) == 1:
        return partial[0]
    if not partial:
        raise ToolInputError(f"no open account matches {name!r}. See ynab_list_accounts.")
    names = ", ".join(repr(a["name"]) for a in partial)
    raise ToolInputError(f"account name {name!r} is ambiguous: {names}. Use the account id.")


def check_payee_args(
    payee_id: str | None,
    payee_name: str | None,
    transfer_account_id: str | None,
    transfer_account_name: str | None,
) -> bool:
    """Network-free argument checks. Returns True when a transfer is requested."""
    if payee_name and _INTERNAL_PAYEE_RE.match(payee_name):
        raise ToolInputError(
            f"payee_name {payee_name!r} looks like a transfer. YNAB rejects it: use "
            "transfer_account_id or transfer_account_name instead."
        )
    is_transfer = bool(transfer_account_id or transfer_account_name)
    if is_transfer and (payee_name or payee_id):
        raise ToolInputError(
            "transfer_account_id/transfer_account_name and payee_name/payee_id are "
            "mutually exclusive."
        )
    if transfer_account_id and transfer_account_name:
        raise ToolInputError("pass transfer_account_id OR transfer_account_name, not both.")
    return is_transfer


async def resolve_payee(
    client: YnabClient,
    budget_id: str,
    *,
    source_account_id: str,
    payee_id: str | None,
    payee_name: str | None,
    transfer_account_id: str | None,
    transfer_account_name: str | None,
    category_id: str | None,
) -> tuple[dict[str, Any], list[str]]:
    """Validate payee/transfer arguments and return the API fields to send.

    Returned dict may contain ``payee_id``, ``payee_name`` and ``category_id``;
    ``category_id`` is present (possibly ``None``) whenever a transfer is set.
    ``source_account_id`` is only read for a transfer.
    """
    is_transfer = check_payee_args(
        payee_id, payee_name, transfer_account_id, transfer_account_name
    )
    if not is_transfer:
        fields: dict[str, Any] = {}
        if payee_id:
            fields["payee_id"] = payee_id
        if payee_name:
            fields["payee_name"] = payee_name
        if category_id:
            fields["category_id"] = category_id
        return fields, []

    accounts = await client.get_accounts(budget_id)
    if not any(a["id"] == source_account_id for a in accounts):
        accounts = await client.get_accounts(budget_id, refresh=True)
    source = find_account(accounts, account_id=source_account_id)
    target = find_account(accounts, account_id=transfer_account_id, name=transfer_account_name)
    if target["id"] == source["id"]:
        raise ToolInputError(f"cannot transfer account {source['name']!r} to itself.")
    if not target.get("transfer_payee_id"):
        raise ToolInputError(f"account {target['name']!r} has no transfer payee.")

    warnings: list[str] = []
    if source.get("on_budget") and not target.get("on_budget"):
        if not category_id:
            raise ToolInputError(
                f"a transfer from on-budget {source['name']!r} to off-budget (tracking) "
                f"account {target['name']!r} needs a category_id (the budget category "
                "the money leaves from / returns to)."
            )
    elif category_id:
        warnings.append(
            f"category_id ignored: a transfer from {source['name']!r} to "
            f"{target['name']!r} carries no category."
        )
        category_id = None
    return {"payee_id": target["transfer_payee_id"], "category_id": category_id}, warnings


async def build_subtransactions(
    client: YnabClient,
    budget_id: str,
    *,
    source_account_id: str,
    parent_milliunits: int,
    items: list[SplitItem],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate split lines (sum, payees, transfers) and return API subtransactions."""
    total = sum(amount_to_milliunits(s.amount) for s in items)
    if total != parent_milliunits:
        raise ToolInputError(
            f"subtransactions must sum to the parent amount: "
            f"{milliunits_to_amount(total)} across {len(items)} splits vs "
            f"{milliunits_to_amount(parent_milliunits)} "
            f"(difference {milliunits_to_amount(parent_milliunits - total)})."
        )
    if len(items) < 2:
        raise ToolInputError("a split needs at least 2 subtransactions.")
    for s in items:
        check_payee_args(s.payee_id, s.payee_name, s.transfer_account_id, s.transfer_account_name)
    subs: list[dict[str, Any]] = []
    warnings: list[str] = []
    for i, s in enumerate(items, start=1):
        try:
            fields, warns = await resolve_payee(
                client,
                budget_id,
                source_account_id=source_account_id,
                payee_id=s.payee_id,
                payee_name=s.payee_name,
                transfer_account_id=s.transfer_account_id,
                transfer_account_name=s.transfer_account_name,
                category_id=s.category_id,
            )
        except ToolInputError as e:
            raise ToolInputError(f"split line {i}: {e}") from e
        warnings.extend(f"split line {i}: {w}" for w in warns)
        if fields.get("category_id") is None:
            fields.pop("category_id", None)
        sub: dict[str, Any] = {"amount": amount_to_milliunits(s.amount), **fields}
        if s.memo:
            sub["memo"] = s.memo
        subs.append(sub)
    return subs, warnings


def is_split(t: dict) -> bool:
    return bool([s for s in t.get("subtransactions") or [] if not s.get("deleted")])


def sub_to_dict(s: dict) -> dict[str, Any]:
    return {
        "id": s.get("id"),
        "amount": milliunits_to_amount(s.get("amount")),
        "category_id": s.get("category_id"),
        "category_name": s.get("category_name"),
        "memo": s.get("memo"),
        "payee_id": s.get("payee_id"),
        "payee_name": s.get("payee_name"),
        "transfer_account_id": s.get("transfer_account_id"),
    }


def txn_to_dict(t: dict, *, include_subtransactions: bool = True) -> dict[str, Any]:
    """Every useful field of a TransactionDetail, amounts in currency units."""
    d: dict[str, Any] = {
        "id": t["id"],
        "date": t.get("date"),
        "amount": milliunits_to_amount(t.get("amount")),
        "account_id": t.get("account_id"),
        "account_name": t.get("account_name"),
        "payee_id": t.get("payee_id"),
        "payee_name": t.get("payee_name"),
        "category_id": t.get("category_id"),
        "category_name": t.get("category_name"),
        "memo": t.get("memo"),
        "cleared": t.get("cleared"),
        "approved": t.get("approved"),
        "flag_color": t.get("flag_color"),
        "import_id": t.get("import_id"),
        "imported": bool(t.get("import_id")),
        "matched_transaction_id": t.get("matched_transaction_id"),
        "transfer_account_id": t.get("transfer_account_id"),
    }
    if include_subtransactions:
        d["subtransactions"] = [
            sub_to_dict(s) for s in t.get("subtransactions") or [] if not s.get("deleted")
        ]
    return d


def txn_line(t: dict[str, Any]) -> str:
    """One Markdown bullet for a ``txn_to_dict`` result (plus indented split lines)."""
    cat = t.get("category_name") or "—"
    marks = ""
    if not t.get("approved"):
        marks += " ⚠️unapproved"
    if t.get("flag_color"):
        marks += f" 🚩{t['flag_color']}"
    if t.get("transfer_account_id"):
        marks += " ↔transfer"
    if t.get("imported"):
        marks += " 🏦imported"
    line = (
        f"- {t['date']} · {t.get('account_name') or '?'} · **{t.get('payee_name') or '?'}** "
        f"· {t['amount']} · [{cat}]{marks} — id `{t['id']}`"
    )
    for s in t.get("subtransactions") or []:
        target = f" ↔ {s['payee_name']}" if s.get("transfer_account_id") else ""
        memo = f" · {s['memo']}" if s.get("memo") else ""
        line += f"\n    - {s['amount']} · [{s.get('category_name') or '—'}]{target}{memo}"
    return line
