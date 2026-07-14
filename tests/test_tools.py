"""End-to-end tool tests: request building + response formatting (HTTP mocked)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from ynab_mcp.config import YNAB_API_BASE, Settings
from ynab_mcp.server import build_server


@pytest.fixture
def server():
    settings = Settings(
        token="test-token",
        default_budget="last-used",
        transport="stdio",
        host="127.0.0.1",
        port=8000,
        timeout=5.0,
    )
    return build_server(settings)


async def call(server, name: str, arguments: dict | None = None) -> str:
    """Invoke a tool and return its text result."""
    result = await server.call_tool(name, arguments or {})
    return result.structured_content["result"]


@respx.mock
async def test_list_accounts_formats_markdown(server):
    respx.get(f"{YNAB_API_BASE}/budgets/last-used/accounts").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "accounts": [
                        {
                            "id": "a1",
                            "name": "Checking",
                            "type": "checking",
                            "on_budget": True,
                            "balance": 12500,
                            "closed": False,
                        },
                        {"id": "a2", "name": "Old", "closed": True, "balance": 0},
                    ]
                }
            },
        )
    )
    out = await call(server, "ynab_list_accounts")

    assert "Checking" in out
    assert "12.5" in out  # milliunits converted
    assert "Old" not in out  # closed account hidden by default


@respx.mock
async def test_list_categories_excludes_internal_inflow(server):
    respx.get(f"{YNAB_API_BASE}/budgets/last-used/categories").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "category_groups": [
                        {
                            "name": "Internal Master Category",
                            "hidden": False,
                            "categories": [
                                {
                                    "id": "inflow",
                                    "name": "Inflow: Ready to Assign",
                                    "budgeted": 0,
                                    "activity": 43342000,
                                    "balance": 43342000,
                                }
                            ],
                        },
                        {
                            "name": "Everyday Expenses",
                            "hidden": False,
                            "categories": [
                                {
                                    "id": "groceries",
                                    "name": "Groceries",
                                    "budgeted": 30000,
                                    "activity": -26000,
                                    "balance": 4000,
                                }
                            ],
                        },
                    ]
                }
            },
        )
    )
    out = await call(server, "ynab_list_categories")

    assert "Inflow: Ready to Assign" not in out
    assert "43342" not in out
    assert "Groceries" in out


@respx.mock
async def test_create_transaction_sends_milliunits(server):
    route = respx.post(f"{YNAB_API_BASE}/budgets/last-used/transactions").mock(
        return_value=httpx.Response(
            201,
            json={
                "data": {
                    "transaction": {
                        "id": "t1",
                        "date": "2026-07-14",
                        "amount": -12500,
                        "payee_name": "Coffee",
                    }
                }
            },
        )
    )
    out = await call(
        server,
        "ynab_create_transaction",
        {"account_id": "a1", "amount": -12.5, "payee_name": "Coffee"},
    )

    body = json.loads(route.calls.last.request.content)
    assert body["transaction"]["amount"] == -12500  # currency -> milliunits
    assert body["transaction"]["account_id"] == "a1"
    assert "t1" in out


@respx.mock
async def test_create_transaction_with_subtransactions(server):
    route = respx.post(f"{YNAB_API_BASE}/budgets/last-used/transactions").mock(
        return_value=httpx.Response(
            201,
            json={
                "data": {
                    "transaction": {
                        "id": "t2",
                        "date": "2026-07-14",
                        "amount": -10000,
                        "payee_name": "Supermarket",
                    }
                }
            },
        )
    )
    out = await call(
        server,
        "ynab_create_transaction",
        {
            "account_id": "a1",
            "amount": -100.0,
            "payee_name": "Supermarket",
            "category_id": "should-be-ignored",
            "subtransactions": [
                {"amount": -60.0, "category_id": "groceries"},
                {"amount": -40.0, "category_id": "household", "memo": "cleaning supplies"},
            ],
        },
    )

    body = json.loads(route.calls.last.request.content)
    subs = body["transaction"]["subtransactions"]
    assert "category_id" not in body["transaction"]
    assert subs == [
        {"amount": -60000, "category_id": "groceries"},
        {"amount": -40000, "category_id": "household", "memo": "cleaning supplies"},
    ]
    assert "2 splits" in out


@respx.mock
async def test_create_transaction_rejects_mismatched_splits(server):
    out = await call(
        server,
        "ynab_create_transaction",
        {
            "account_id": "a1",
            "amount": -100.0,
            "subtransactions": [{"amount": -60.0, "category_id": "groceries"}],
        },
    )
    assert "must sum to" in out.lower()


@respx.mock
async def test_error_maps_to_friendly_message(server):
    respx.get(f"{YNAB_API_BASE}/budgets").mock(return_value=httpx.Response(401))
    out = await call(server, "ynab_list_budgets")
    assert "token" in out.lower()
