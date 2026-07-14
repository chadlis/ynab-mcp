"""Tests for the YnabClient HTTP wrapper and error mapping (HTTP mocked)."""

from __future__ import annotations

import httpx
import pytest
import respx

from ynab_mcp.config import YNAB_API_BASE
from ynab_mcp.errors import handle_api_error


@respx.mock
async def test_request_sends_auth_and_returns_data(client):
    route = respx.get(f"{YNAB_API_BASE}/budgets").mock(
        return_value=httpx.Response(200, json={"data": {"budgets": [{"id": "b1"}]}})
    )
    data = await client.request("GET", "/budgets")

    assert data == {"budgets": [{"id": "b1"}]}
    sent = route.calls.last.request
    assert sent.headers["Authorization"] == "Bearer test-token"


@respx.mock
async def test_request_forwards_json_body(client):
    route = respx.post(f"{YNAB_API_BASE}/budgets/last-used/transactions").mock(
        return_value=httpx.Response(201, json={"data": {"transaction": {"id": "t1"}}})
    )
    body = {"transaction": {"amount": -12500}}
    data = await client.request("POST", "/budgets/last-used/transactions", json_body=body)

    assert data == {"transaction": {"id": "t1"}}
    import json

    assert json.loads(route.calls.last.request.content) == body


@respx.mock
async def test_request_raises_on_http_error(client):
    respx.get(f"{YNAB_API_BASE}/budgets").mock(return_value=httpx.Response(401))
    with pytest.raises(httpx.HTTPStatusError):
        await client.request("GET", "/budgets")


def test_missing_token_raises(settings):
    from dataclasses import replace

    from ynab_mcp.client import YnabClient

    c = YnabClient(replace(settings, token=""))
    with pytest.raises(RuntimeError, match="YNAB_TOKEN"):
        c._get_client()


def _status_error(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://api.ynab.com/v1/budgets")
    response = httpx.Response(code, text="boom", request=request)
    return httpx.HTTPStatusError("err", request=request, response=response)


@pytest.mark.parametrize(
    ("code", "needle"),
    [(401, "token"), (404, "not found"), (429, "rate limit"), (500, "500")],
)
def test_handle_api_error_status(code, needle):
    assert needle in handle_api_error(_status_error(code)).lower()


def test_handle_api_error_timeout():
    assert "timed out" in handle_api_error(httpx.TimeoutException("slow")).lower()
