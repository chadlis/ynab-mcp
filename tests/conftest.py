"""Shared test fixtures."""

from __future__ import annotations

import pytest

from ynab_mcp.client import YnabClient
from ynab_mcp.config import Settings


@pytest.fixture
def settings() -> Settings:
    """Deterministic settings with a fake token (no .env / env dependence)."""
    return Settings(
        token="test-token",
        default_budget="last-used",
        transport="stdio",
        host="127.0.0.1",
        port=8000,
        timeout=5.0,
    )


@pytest.fixture
async def client(settings: Settings) -> YnabClient:
    """A YnabClient bound to the fake settings; closed after the test."""
    c = YnabClient(settings)
    try:
        yield c
    finally:
        await c.aclose()
