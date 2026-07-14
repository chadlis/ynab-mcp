# ynab-mcp

An [MCP](https://modelcontextprotocol.io) server that exposes your
[YNAB](https://www.ynab.com) (You Need A Budget) budget to MCP clients such as
Claude Desktop and claude.ai.

## Tools

**Read**
- `ynab_list_budgets` — budgets accessible with your token
- `ynab_list_accounts` — accounts and balances of a budget
- `ynab_list_categories` — category groups with budgeted / activity / balance
- `ynab_list_payees` — payees (paginated)
- `ynab_list_transactions` — transactions with filters (account, category, date, type)
- `ynab_get_budget_month` — monthly summary (to-be-budgeted, income, activity, age of money)

**Write**
- `ynab_create_transaction` — create a transaction (amount in currency units, negative = expense)
- `ynab_update_transaction` — partially update a transaction (categorize, approve, memo…)

## Requirements

- [uv](https://docs.astral.sh/uv/)
- A YNAB **Personal Access Token** — YNAB → Account Settings → Developer Settings → New Token

## Setup

```bash
uv sync                       # install dependencies
cp .env.example .env          # then put your token in .env
```

`.env`:

```dotenv
YNAB_TOKEN=your-token-here
YNAB_BUDGET_ID=               # optional; empty = use YNAB's "last-used" budget
```

Run it:

```bash
uv run ynab-mcp
```

## Use with Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "ynab": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/ynab-mcp", "ynab-mcp"],
      "env": { "YNAB_TOKEN": "your-token-here" }
    }
  }
}
```

## Remote (HTTP) hosting

Set `MCP_TRANSPORT=http` to serve over streamable-http (endpoint `/mcp`):

```bash
MCP_TRANSPORT=http HOST=0.0.0.0 PORT=8000 uv run ynab-mcp
```

## Conventions

- Amounts are in normal currency units; **an expense is negative** (e.g. `-12.50`).
  Conversion to/from YNAB milliunits is automatic.
- `budget_id` defaults to `YNAB_BUDGET_ID`, or the `"last-used"` budget if unset.
- YNAB rate limit: 200 requests / hour / token.

## Development

```bash
uv sync --extra dev
uv run pytest          # tests (HTTP mocked, no network)
uv run ruff check .    # lint
```

## Security

Never commit `.env` — it contains a live token and is gitignored. If a token
leaks, rotate it in YNAB's Developer Settings.

## License

MIT
