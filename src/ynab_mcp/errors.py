"""Uniform, actionable error messages shared by every tool."""

from __future__ import annotations

import httpx


class ToolInputError(Exception):
    """Invalid tool arguments, detected before any write call to the API."""


# (substring of YNAB's error detail, lowercase) -> suggested next action.
_DETAIL_HINTS = [
    (
        "payee name must not start with",
        "For a transfer, pass transfer_account_id or transfer_account_name instead of "
        "payee_name.",
    ),
    (
        "subtransaction",
        "Splits can only be set on a transaction that is not already split. Use "
        "ynab_get_transaction to inspect it.",
    ),
    ("category", "Check the category_id with ynab_list_categories."),
    ("account", "Check the account with ynab_list_accounts."),
    ("payee", "Check the payee_id with ynab_list_payees."),
    ("date", "Dates must be YYYY-MM-DD and not more than 5 years in the past or in the future."),
]


def _ynab_detail(response: httpx.Response) -> str:
    """Extract YNAB's ``error.detail`` (falls back to the raw body)."""
    try:
        err = response.json().get("error") or {}
        return str(err.get("detail") or err.get("name") or "").strip()
    except Exception:  # noqa: BLE001
        return response.text[:200].strip()


def _hint(detail: str) -> str:
    low = detail.lower()
    for needle, hint in _DETAIL_HINTS:
        if needle in low:
            return f" Suggestion: {hint}"
    return ""


def handle_api_error(e: Exception) -> str:
    """Map an exception raised during a YNAB call to a single user-facing message."""
    if isinstance(e, ToolInputError):
        return f"Error: {e} (no change was sent to YNAB)"
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        detail = _ynab_detail(e.response)
        if code == 401:
            return (
                "Error: invalid or missing YNAB token. Check the YNAB_TOKEN "
                "environment variable (Account Settings > Developer Settings)."
            )
        if code == 404:
            return (
                f"Error: resource not found ({detail or 'no detail'}). "
                "Check the budget_id / account_id / id."
            )
        if code == 429:
            return (
                "Error: rate limit reached (200 requests/hour). "
                "Wait for the next full hour before retrying."
            )
        return f"Error: the YNAB API responded {code} — {detail or 'no detail'}.{_hint(detail)}"
    if isinstance(e, httpx.TimeoutException):
        return "Error: request timed out. Please retry."
    return f"Unexpected error: {type(e).__name__}: {e}"
