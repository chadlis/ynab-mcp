"""Manual smoke test: spawn the stdio server, handshake, list tools.

Run with: uv run python scripts/smoke_client.py
Set YNAB_TOKEN to also call a live read tool (ynab_list_budgets).
"""

from __future__ import annotations

import asyncio
import os

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    params = StdioServerParameters(command="uv", args=["run", "ynab-mcp"], env=dict(os.environ))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print(f"Connected. {len(tools.tools)} tools:")
            for t in tools.tools:
                print(f"  - {t.name}")

            if os.environ.get("YNAB_TOKEN"):
                print("\nCalling ynab_list_budgets (live)...")
                result = await session.call_tool("ynab_list_budgets", {})
                print(result.content[0].text)
            else:
                print("\n(Set YNAB_TOKEN to also test a live API call.)")


if __name__ == "__main__":
    asyncio.run(main())
