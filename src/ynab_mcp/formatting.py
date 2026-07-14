"""Amount conversions, pagination, and response formatting helpers."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any


class ResponseFormat(StrEnum):
    """How a tool should render its result."""

    MARKDOWN = "markdown"
    JSON = "json"


def milliunits_to_amount(milliunits: int | None) -> float | None:
    """12500 -> 12.50 (YNAB stores amounts in thousandths of a currency unit)."""
    if milliunits is None:
        return None
    return round(milliunits / 1000, 2)


def amount_to_milliunits(amount: float) -> int:
    """12.50 -> 12500 (negative = expense/outflow, positive = income/inflow)."""
    return int(round(amount * 1000))


def to_json(obj: Any) -> str:
    """Pretty-print an object as UTF-8 JSON."""
    return json.dumps(obj, indent=2, ensure_ascii=False)


def paginate(items: list, limit: int, offset: int) -> dict:
    """Client-side pagination (the YNAB API returns full collections at once)."""
    total = len(items)
    window = items[offset : offset + limit]
    consumed = offset + len(window)
    has_more = consumed < total
    return {
        "total": total,
        "count": len(window),
        "offset": offset,
        "items": window,
        "has_more": has_more,
        "next_offset": consumed if has_more else None,
    }
