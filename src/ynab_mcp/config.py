"""Runtime configuration, loaded from environment variables (and an optional .env).

Key YNAB conventions handled by this server:
- API v1 base URL: https://api.ynab.com/v1
- budget_id: the "last-used" shortcut targets the most recently opened budget.
- milliunits: YNAB stores amounts in thousandths of a currency unit (12.50 => 12500).
  An outflow (expense) is NEGATIVE, an inflow (income) is POSITIVE.
- Rate limit: 200 requests / hour / token.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# The YNAB "last-used" shortcut: the most recently used budget.
LAST_USED_BUDGET = "last-used"
YNAB_API_BASE = "https://api.ynab.com/v1"


@dataclass(frozen=True)
class Settings:
    """Immutable settings resolved once at startup."""

    token: str
    default_budget: str
    transport: str
    host: str
    port: int
    timeout: float

    @classmethod
    def from_env(cls) -> Settings:
        """Build settings from the process environment.

        Loads a local .env if present (no-op when the file is missing), so the
        server works both from `uv run` and when an MCP client injects env vars.
        """
        load_dotenv()
        # An explicit default budget id takes precedence; otherwise fall back to
        # YNAB's "last-used" shortcut so the server works with no extra config.
        default_budget = os.environ.get("YNAB_BUDGET_ID", "").strip() or LAST_USED_BUDGET
        return cls(
            token=os.environ.get("YNAB_TOKEN", "").strip(),
            default_budget=default_budget,
            transport=os.environ.get("MCP_TRANSPORT", "stdio").strip().lower(),
            host=os.environ.get("HOST", "0.0.0.0"),
            port=int(os.environ.get("PORT", "8000")),
            timeout=float(os.environ.get("YNAB_TIMEOUT", "30")),
        )
