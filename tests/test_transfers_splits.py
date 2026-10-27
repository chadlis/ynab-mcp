"""Transfers, splits, deletion, bulk updates and budgeting tools (HTTP mocked)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from ynab_mcp.config import YNAB_API_BASE, Settings
from ynab_mcp.server import build_server
from ynab_mcp.tools._txn import normalize_name

B = f"{YNAB_API_BASE}/budgets/last-used"

ACCOUNTS = [
    {"id": "rev", "name": "Revolut", "type": "checking", "on_budget": True,
     "closed": False, "balance": 0, "transfer_payee_id": "p-rev"},
    {"id": "liv", "name": "Livret A", "type": "savings", "on_budget": True,
     "closed": False, "balance": 0, "transfer_payee_id": "p-liv"},
    {"id": "mut", "name": "♻️ Mutuelle — avances", "type": "otherAsset", "on_budget": False,
     "closed": False, "balance": 0, "transfer_payee_id": "p-mut"},
    {"id": "ima", "name": "imane (non réccurent)", "type": "personalLoan", "on_budget": False,
     "closed": False, "balance": 0, "transfer_payee_id": "p-ima"},
]


def txn(**overrides) -> dict:
    t = {
        "id": "t1", "date": "2026-10-20", "amount": -63210, "account_id": "rev",
        "account_name": "Revolut", "payee_id": "p-amz", "payee_name": "Amazon",
        "category_id": None, "category_name": None, "memo": None, "cleared": "cleared",
        "approved": False, "flag_color": None, "import_id": "YNAB:-63210:2026-10-20:1",
        "matched_transaction_id": None, "transfer_account_id": None,
        "subtransactions": [], "deleted": False,
    }
    t.update(overrides)
    return t


@pytest.fixture
def server():
    return build_server(
        Settings(token="test-token", default_budget="last-used", transport="stdio",
                 host="127.0.0.1", port=8000, timeout=5.0)
    )


async def call(server, name: str, arguments: dict | None = None) -> str:
    result = await server.call_tool(name, arguments or {})
    return result.structured_content["result"]


def mock_accounts():
    return respx.get(f"{B}/accounts").mock(
        return_value=httpx.Response(200, json={"data": {"accounts": ACCOUNTS}})
    )


def body(route) -> dict:
    return json.loads(route.calls.last.request.content)


def test_normalize_name_ignores_case_accents_emoji_punctuation():
    assert normalize_name("♻️ Mutuelle — avances") == "mutuelle avances"
    assert normalize_name("imane (non réccurent)") == normalize_name("Imane non reccurent")


@respx.mock
async def test_list_accounts_exposes_transfer_payee_id(server):
    mock_accounts()
    out = await call(server, "ynab_list_accounts", {"response_format": "json"})
    assert json.loads(out)[2]["transfer_payee_id"] == "p-mut"


# Acceptance 1: off-budget transfer with category.
@respx.mock
async def test_update_to_off_budget_transfer_with_category(server):
    accounts = mock_accounts()
    respx.get(f"{B}/transactions/t1").mock(
        return_value=httpx.Response(200, json={"data": {"transaction": txn(amount=38220)}})
    )
    patch = respx.patch(f"{B}/transactions/t1").mock(
        return_value=httpx.Response(200, json={"data": {"transaction": txn(
            amount=38220, payee_name="Transfer : ♻️ Mutuelle — avances",
            transfer_account_id="mut", category_name="♻️ mutuelle — avances", approved=True,
        )}})
    )
    out = await call(server, "ynab_update_transaction", {
        "transaction_id": "t1", "transfer_account_name": "mutuelle — avances",
        "category_id": "cat-mut", "approved": True,
    })
    assert body(patch)["transaction"] == {
        "payee_id": "p-mut", "category_id": "cat-mut", "approved": True,
    }
    assert "Transfer : ♻️ Mutuelle — avances" in out
    # Second transfer within the TTL reuses the cached accounts.
    await call(server, "ynab_update_transaction", {
        "transaction_id": "t1", "transfer_account_id": "mut", "category_id": "cat-mut",
    })
    assert accounts.call_count == 1


@respx.mock
async def test_off_budget_transfer_without_category_is_refused(server):
    mock_accounts()
    respx.get(f"{B}/transactions/t1").mock(
        return_value=httpx.Response(200, json={"data": {"transaction": txn()}})
    )
    patch = respx.patch(f"{B}/transactions/t1")
    out = await call(server, "ynab_update_transaction", {
        "transaction_id": "t1", "transfer_account_name": "mutuelle avances",
    })
    assert "needs a category_id" in out
    assert not patch.called


@respx.mock
async def test_on_budget_transfer_drops_category_and_warns(server):
    mock_accounts()
    post = respx.post(f"{B}/transactions").mock(
        return_value=httpx.Response(201, json={"data": {"transaction": txn(id="new")}})
    )
    out = await call(server, "ynab_create_transaction", {
        "account_id": "rev", "amount": -50, "transfer_account_name": "livret a",
        "category_id": "cat-x",
    })
    sent = body(post)["transaction"]
    assert sent["payee_id"] == "p-liv"
    assert "category_id" not in sent
    assert "category_id ignored" in out


# Acceptance 3: clean refusal, no API call.
@respx.mock
async def test_transfer_payee_name_refused_without_api_call(server):
    out = await call(server, "ynab_update_transaction", {
        "transaction_id": "t1", "payee_name": "Transfer : Livret A",
    })
    assert "transfer_account_id" in out
    assert len(respx.calls) == 0


@respx.mock
async def test_transfer_and_payee_name_are_exclusive(server):
    out = await call(server, "ynab_create_transaction", {
        "account_id": "rev", "amount": -1, "payee_name": "X", "transfer_account_id": "liv",
    })
    assert "mutually exclusive" in out
    assert len(respx.calls) == 0


# Acceptance 2: split with a transfer line, in place (import_id kept).
@respx.mock
async def test_split_transaction_with_transfer_line(server):
    mock_accounts()
    respx.get(f"{B}/transactions/t1").mock(
        return_value=httpx.Response(200, json={"data": {"transaction": txn()}})
    )
    put = respx.put(f"{B}/transactions/t1").mock(
        return_value=httpx.Response(200, json={"data": {"transaction": txn(
            category_name="Split", approved=True,
            subtransactions=[
                {"id": "s1", "amount": -55550, "category_id": "cat-hh",
                 "category_name": "🧴 household supplies"},
                {"id": "s2", "amount": -7660, "category_id": "cat-ima",
                 "category_name": "♻️ imane (non réccurent)", "payee_id": "p-ima",
                 "payee_name": "Transfer : imane (non réccurent)", "transfer_account_id": "ima"},
            ],
        )}})
    )
    out = await call(server, "ynab_split_transaction", {
        "transaction_id": "t1", "approved": True,
        "subtransactions": [
            {"amount": -55.55, "category_id": "cat-hh"},
            {"amount": -7.66, "transfer_account_name": "Imane (non reccurent)",
             "category_id": "cat-ima"},
        ],
    })
    sent = body(put)["transaction"]
    assert sent["category_id"] is None
    assert sent["amount"] == -63210 and sent["account_id"] == "rev"
    assert sent["subtransactions"] == [
        {"amount": -55550, "category_id": "cat-hh"},
        {"amount": -7660, "payee_id": "p-ima", "category_id": "cat-ima"},
    ]
    assert "split into 2 lines" in out
    assert "import_id kept=True" in out


# Acceptance 4: wrong sum refused before any write.
@respx.mock
async def test_split_wrong_sum_refused_before_write(server):
    respx.get(f"{B}/transactions/t1").mock(
        return_value=httpx.Response(200, json={"data": {"transaction": txn()}})
    )
    put = respx.put(f"{B}/transactions/t1")
    out = await call(server, "ynab_split_transaction", {
        "transaction_id": "t1",
        "subtransactions": [{"amount": -55.55, "category_id": "a"},
                            {"amount": -7.65, "category_id": "b"}],
    })
    assert "must sum to" in out and "-0.01" in out
    assert not put.called


@respx.mock
async def test_split_refuses_already_split_and_reconciled(server):
    route = respx.get(f"{B}/transactions/t1")
    route.mock(return_value=httpx.Response(200, json={"data": {"transaction": txn(
        subtransactions=[{"id": "s", "amount": -63210}])}}))
    args = {"transaction_id": "t1", "subtransactions": [
        {"amount": -60, "category_id": "a"}, {"amount": -3.21, "category_id": "b"}]}
    assert "already split" in await call(server, "ynab_split_transaction", args)
    route.mock(return_value=httpx.Response(
        200, json={"data": {"transaction": txn(cleared="reconciled")}}))
    assert "reconciled" in await call(server, "ynab_split_transaction", args)


@respx.mock
async def test_split_reports_when_api_ignores_subtransactions(server):
    respx.get(f"{B}/transactions/t1").mock(
        return_value=httpx.Response(200, json={"data": {"transaction": txn()}})
    )
    respx.put(f"{B}/transactions/t1").mock(
        return_value=httpx.Response(200, json={"data": {"transaction": txn()}})
    )
    out = await call(server, "ynab_split_transaction", {
        "transaction_id": "t1", "subtransactions": [
            {"amount": -60, "category_id": "a"}, {"amount": -3.21, "category_id": "b"}],
    })
    assert out.startswith("Error") and "not split" in out


# Acceptance 5: delete requires confirm.
@respx.mock
async def test_delete_requires_confirm(server):
    get = respx.get(f"{B}/transactions/t1").mock(
        return_value=httpx.Response(200, json={"data": {"transaction": txn()}})
    )
    delete = respx.delete(f"{B}/transactions/t1").mock(
        return_value=httpx.Response(200, json={"data": {"transaction": txn(deleted=True)}})
    )
    out = await call(server, "ynab_delete_transaction", {"transaction_id": "t1"})
    assert "confirm=true" in out and not get.called and not delete.called

    out = await call(server, "ynab_delete_transaction", {"transaction_id": "t1", "confirm": True})
    assert delete.called
    assert "2026-10-20" in out and "Amazon" in out and "-63.21" in out and "Revolut" in out


@respx.mock
async def test_delete_refuses_reconciled(server):
    respx.get(f"{B}/transactions/t1").mock(
        return_value=httpx.Response(200, json={"data": {"transaction": txn(cleared="reconciled")}})
    )
    delete = respx.delete(f"{B}/transactions/t1")
    out = await call(server, "ynab_delete_transaction", {"transaction_id": "t1", "confirm": True})
    assert "reconciled" in out and not delete.called


# Acceptance 6: approve 30 transactions in one call.
@respx.mock
async def test_bulk_approve_30_in_one_call(server):
    ids = [f"t{i}" for i in range(30)]

    def reply(request):
        sent = json.loads(request.content)["transactions"]
        return httpx.Response(
            209, headers={"X-Rate-Limit": "42/200"},
            json={"data": {
                "transaction_ids": [t["id"] for t in sent[:-1]],  # last one "unknown"
                "transactions": [txn(id=t["id"], approved=True) for t in sent[:-1]],
            }},
        )

    patch = respx.patch(f"{B}/transactions").mock(side_effect=reply)
    out = await call(server, "ynab_update_transactions", {
        "transactions": [{"id": i, "approved": True} for i in ids]
        + [{"id": "bad", "payee_name": "Transfer : X"}],
    })
    assert patch.call_count == 1
    assert len(respx.calls) == 1
    assert len(body(patch)["transactions"]) == 30
    assert "29 succeeded, 2 failed" in out
    assert "`bad`" in out and "`t29`" in out
    assert "42/200" in out and "158 left" in out


@respx.mock
async def test_bulk_rejects_more_than_100(server):
    with pytest.raises(Exception):  # noqa: B017 - pydantic validation error
        await server.call_tool(
            "ynab_update_transactions",
            {"transactions": [{"id": str(i), "approved": True} for i in range(101)]},
        )


@respx.mock
async def test_bulk_transfer_resolves_source_account(server):
    mock_accounts()
    respx.get(f"{B}/transactions").mock(
        return_value=httpx.Response(200, json={"data": {"transactions": [txn()]}})
    )
    patch = respx.patch(f"{B}/transactions").mock(
        return_value=httpx.Response(200, json={"data": {"transaction_ids": ["t1"]}})
    )
    await call(server, "ynab_update_transactions", {
        "transactions": [{"id": "t1", "transfer_account_name": "livret a", "approved": True}],
    })
    assert body(patch)["transactions"] == [
        {"id": "t1", "payee_id": "p-liv", "category_id": None, "approved": True}
    ]


# Acceptance 7: split lines visible.
@respx.mock
async def test_get_transaction_shows_split_lines(server):
    respx.get(f"{B}/transactions/t1").mock(
        return_value=httpx.Response(200, json={"data": {"transaction": txn(
            category_name="Split",
            subtransactions=[
                {"id": "s1", "amount": -55550, "category_name": "🧴 household supplies"},
                {"id": "s2", "amount": -7660, "category_name": "♻️ imane",
                 "transfer_account_id": "ima", "payee_name": "Transfer : imane"},
                {"id": "s3", "amount": 0, "deleted": True},
            ],
        )}})
    )
    out = await call(server, "ynab_get_transaction", {"transaction_id": "t1"})
    assert "Splits (2)" in out
    assert "🧴 household supplies" in out and "transfer → `ima`" in out
    assert "import_id: YNAB:-63210" in out


@respx.mock
async def test_list_transactions_enriched_and_filtered(server):
    respx.get(f"{B}/transactions").mock(
        return_value=httpx.Response(200, json={"data": {"transactions": [
            txn(),
            txn(id="t2", amount=-12000, payee_name="Carrefour"),
            txn(id="t3", date="2026-10-25"),
            txn(id="t4", account_name="Livret A"),
            txn(id="t5", category_name="Split", subtransactions=[
                {"id": "s1", "amount": -63210, "category_name": "Groceries"}]),
        ]}})
    )
    out = await call(server, "ynab_list_transactions", {
        "until_date": "2026-10-21", "payee_contains": "amaz", "amount": -63.21,
        "account_name": "revolut", "include_subtransactions": True, "response_format": "json",
    })
    items = json.loads(out)["items"]
    assert [t["id"] for t in items] == ["t1", "t5"]
    assert items[0]["account_name"] == "Revolut" and items[0]["imported"] is True
    assert "flag_color" in items[0] and "transfer_account_id" in items[0]
    assert items[1]["subtransactions"][0]["category_name"] == "Groceries"


@respx.mock
async def test_api_error_includes_ynab_detail_and_hint(server):
    respx.post(f"{B}/transactions").mock(return_value=httpx.Response(400, json={"error": {
        "id": "400", "name": "bad_request",
        "detail": "payee name must not start with an internal payee name"}}))
    out = await call(server, "ynab_create_transaction", {"account_id": "a", "amount": -1,
                                                          "payee_name": "Starting Balance x"})
    assert "must not start with" in out and "transfer_account_id" in out


@respx.mock
async def test_move_money(server):
    respx.get(f"{B}/months/current/categories/a").mock(return_value=httpx.Response(
        200, json={"data": {"category": {"name": "A", "budgeted": 100000}}}))
    respx.get(f"{B}/months/current/categories/b").mock(return_value=httpx.Response(
        200, json={"data": {"category": {"name": "B", "budgeted": 5000}}}))
    pa = respx.patch(f"{B}/months/current/categories/a").mock(return_value=httpx.Response(
        200, json={"data": {"category": {"name": "A", "budgeted": 75000, "balance": 1000}}}))
    pb = respx.patch(f"{B}/months/current/categories/b").mock(return_value=httpx.Response(
        200, json={"data": {"category": {"name": "B", "budgeted": 30000, "balance": 0}}}))
    out = await call(server, "ynab_move_money", {
        "from_category_id": "a", "to_category_id": "b", "amount": 25})
    assert body(pa) == {"category": {"budgeted": 75000}}
    assert body(pb) == {"category": {"budgeted": 30000}}
    assert "Moved 25" in out


@respx.mock
async def test_set_category_budgeted(server):
    route = respx.patch(f"{B}/months/2026-10-01/categories/a").mock(return_value=httpx.Response(
        200, json={"data": {"category": {"name": "A", "budgeted": 12340}}}))
    out = await call(server, "ynab_set_category_budgeted", {
        "category_id": "a", "budgeted": 12.34, "month": "2026-10-01"})
    assert body(route) == {"category": {"budgeted": 12340}}
    assert "12.34" in out
