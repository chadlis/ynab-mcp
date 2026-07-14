"""Thin async wrapper around the YNAB REST API.

Holds a single reusable ``httpx.AsyncClient`` (connection pooling) instead of
opening a new client on every request.
"""

from __future__ import annotations

from typing import Any

import httpx

from ynab_mcp.config import YNAB_API_BASE, Settings


class YnabClient:
    """Reusable client for the YNAB v1 API."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: httpx.AsyncClient | None = None

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
        resp = await client.request(method, path, params=params, json=json_body)
        resp.raise_for_status()
        return resp.json()["data"]

    async def aclose(self) -> None:
        """Close the underlying connection pool."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
