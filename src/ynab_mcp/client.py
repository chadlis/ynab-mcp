"""Thin async wrapper around the YNAB REST API.

Holds a single reusable ``httpx.AsyncClient`` (connection pooling) instead of
opening a new client on every request. Also tracks the hourly request quota
and caches each budget's accounts (needed to resolve transfer payees).
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any

import httpx

from ynab_mcp.config import YNAB_API_BASE, Settings

RATE_LIMIT_PER_HOUR = 200
ACCOUNTS_TTL_SECONDS = 600


class YnabClient:
    """Reusable client for the YNAB v1 API."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: httpx.AsyncClient | None = None
        # Timestamps of requests sent in the last hour (local fallback count).
        self._request_times: deque[float] = deque()
        # Last value of YNAB's `X-Rate-Limit: <used>/<limit>` header.
        self._rate_header: tuple[int, int] | None = None
        # budget_id -> (fetched_at, accounts)
        self._accounts: dict[str, tuple[float, list[dict[str, Any]]]] = {}

    @property
    def default_budget(self) -> str:
        return self._settings.default_budget

    def _get_client(self) -> httpx.AsyncClient:
        """Lazily create the shared client (bound to the running event loop)."""
        if self._client is None or self._client.is_closed:
            if not self._settings.token:
                raise RuntimeError("YNAB_TOKEN is missing.")
            self._client = httpx.AsyncClient(
                base_url=YNAB_API_BASE,
                timeout=self._settings.timeout,
                headers={
                    "Authorization": f"Bearer {self._settings.token}",
                    "Accept": "application/json",
                },
            )
        return self._client

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
    ) -> dict[str, Any]:
        """Perform a request and return the ``data`` envelope from the response."""
        client = self._get_client()
        self._request_times.append(time.monotonic())
        resp = await client.request(method, path, params=params, json=json_body)
        self._record_rate_header(resp)
        resp.raise_for_status()
        if resp.status_code == 204 or not resp.content:
            return {}
        return resp.json()["data"]

    def _record_rate_header(self, resp: httpx.Response) -> None:
        raw = resp.headers.get("X-Rate-Limit", "")
        used, _, limit = raw.partition("/")
        if used.strip().isdigit() and limit.strip().isdigit():
            self._rate_header = (int(used), int(limit))

    def rate_limit_status(self) -> str:
        """Human-readable remaining quota (YNAB header if seen, else local count)."""
        if self._rate_header is not None:
            used, limit = self._rate_header
            source = "per YNAB"
        else:
            cutoff = time.monotonic() - 3600
            while self._request_times and self._request_times[0] < cutoff:
                self._request_times.popleft()
            used, limit = len(self._request_times), RATE_LIMIT_PER_HOUR
            source = "counted by this server since start"
        return f"API quota: {used}/{limit} used this hour, {max(limit - used, 0)} left ({source})"

    async def get_accounts(self, budget_id: str, *, refresh: bool = False) -> list[dict]:
        """Return the budget's raw accounts, cached for ``ACCOUNTS_TTL_SECONDS``."""
        cached = self._accounts.get(budget_id)
        if cached and not refresh and time.monotonic() - cached[0] < ACCOUNTS_TTL_SECONDS:
            return cached[1]
        data = await self.request("GET", f"/budgets/{budget_id}/accounts")
        accounts = [a for a in data.get("accounts", []) if not a.get("deleted")]
        self.prime_accounts(budget_id, accounts)
        return accounts

    def prime_accounts(self, budget_id: str, accounts: list[dict]) -> None:
        """Store a freshly fetched account list in the cache."""
        self._accounts[budget_id] = (time.monotonic(), accounts)

    async def aclose(self) -> None:
        """Close the underlying connection pool."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
