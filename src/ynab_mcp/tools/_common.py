"""Shared tool annotations."""

from __future__ import annotations

# MCP tool annotations for read-only tools.
READ_ONLY = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}

# MCP tool annotations for write tools that create new resources.
WRITE_CREATE = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": False,
    "openWorldHint": True,
}

# MCP tool annotations for write tools that update existing resources.
WRITE_UPDATE = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}

# MCP tool annotations for write tools that delete resources.
DESTRUCTIVE = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": True,
    "openWorldHint": True,
}
