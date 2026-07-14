"""Unit tests for pure formatting/conversion helpers."""

from __future__ import annotations

import json

import pytest

from ynab_mcp.formatting import (
    amount_to_milliunits,
    milliunits_to_amount,
    paginate,
    to_json,
)


@pytest.mark.parametrize(
    ("milliunits", "expected"),
    [(12500, 12.5), (-12500, -12.5), (0, 0.0), (None, None), (1, 0.0)],
)
def test_milliunits_to_amount(milliunits, expected):
    assert milliunits_to_amount(milliunits) == expected


@pytest.mark.parametrize(
    ("amount", "expected"),
    [(12.5, 12500), (-12.5, -12500), (0, 0), (1.005, 1005)],
)
def test_amount_to_milliunits(amount, expected):
    assert amount_to_milliunits(amount) == expected


def test_round_trip():
    assert milliunits_to_amount(amount_to_milliunits(-42.42)) == -42.42


def test_paginate_first_page():
    page = paginate(list(range(10)), limit=3, offset=0)
    assert page["items"] == [0, 1, 2]
    assert page["count"] == 3
    assert page["total"] == 10
    assert page["has_more"] is True
    assert page["next_offset"] == 3


def test_paginate_last_page():
    page = paginate(list(range(10)), limit=3, offset=9)
    assert page["items"] == [9]
    assert page["has_more"] is False
    assert page["next_offset"] is None


def test_paginate_beyond_end():
    page = paginate(list(range(3)), limit=5, offset=10)
    assert page["items"] == []
    assert page["has_more"] is False


def test_to_json_is_utf8_and_pretty():
    out = to_json({"name": "Café", "n": 1})
    assert json.loads(out) == {"name": "Café", "n": 1}
    assert "Café" in out  # not escaped
    assert "\n" in out  # indented
