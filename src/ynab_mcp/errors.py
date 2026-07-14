"""Uniform, actionable error messages shared by every tool."""

from __future__ import annotations

import httpx


def handle_api_error(e: Exception) -> str:
    """Map an exception raised during a YNAB call to a single user-facing message."""
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        if code == 401:
            return (
                "Error: invalid or missing YNAB token. Check the YNAB_TOKEN "
                "environment variable (Account Settings > Developer Settings)."
            )
        if code == 404:
            return "Error: resource not found. Check the budget_id / account_id / id."
        if code == 429:
            return (
                "Error: rate limit reached (200 requests/hour). "
                "Wait for the next full hour before retrying."
            )
        return f"Error: the YNAB API responded {code} — {e.response.text[:200]}"
    if isinstance(e, httpx.TimeoutException):
        return "Error: request timed out. Please retry."
    return f"Unexpected error: {type(e).__name__}: {e}"
