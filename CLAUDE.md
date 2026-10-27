# CLAUDE.md

Guidance for Claude Code (and other agents) working in this repository.

## What this is

An MCP server that exposes the **YNAB (You Need A Budget)** API to MCP clients
(Claude Desktop, claude.ai, etc.). It offers read tools (budgets, accounts,
categories, payees, transactions, single transaction, month summary) and write
tools (create / update / bulk-update / split / delete transactions, assign and
move category money). Managed with **uv**.

## Commands

```bash
uv sync --extra dev          # install runtime + dev dependencies
uv run ynab-mcp              # run the server (stdio transport by default)
uv run pytest                # run the test suite (no network — HTTP is mocked)
uv run pytest -q tests/test_tools.py::test_create_transaction_sends_milliunits
uv run ruff check .          # lint
uv run ruff check --fix .    # lint + autofix
```

If a stale `VIRTUAL_ENV` from another project is exported in the shell, prefix
uv commands with `env -u VIRTUAL_ENV` so uv uses this project's `.venv`.

## Architecture

Source lives under `src/ynab_mcp/` (src-layout, installed package):

- `config.py` — `Settings.from_env()` resolves all runtime config from env vars
  (loads a local `.env` if present). `default_budget` prefers `YNAB_BUDGET_ID`,
  else falls back to the `"last-used"` shortcut.
- `client.py` — `YnabClient` wraps a **single reusable** `httpx.AsyncClient`
  (base URL, auth header, timeout). `request()` returns the API's `data` envelope.
  It also tracks the hourly quota (`rate_limit_status()`, from YNAB's
  `X-Rate-Limit` header) and caches accounts per budget for 10 min
  (`get_accounts()`), used to resolve transfer payees.
- `errors.py` — `handle_api_error()` maps exceptions to one friendly message
  (401 token, 404 not found, 429 rate limit, timeouts; other codes carry YNAB's
  `error.detail` plus a suggestion). Raise `ToolInputError` for argument
  validation failures detected before any write.
- `formatting.py` — milliunits <-> amount conversion, `paginate()`, `to_json()`,
  and the `ResponseFormat` enum (markdown | json).
- `server.py` — `build_server()` creates the `FastMCP` instance and registers
  tools. The module-level `mcp = build_server()` is the default instance used
  by both `main()` (console entry point, picks the transport) and by any
  `module:object` deploy target (e.g. FastMCP Cloud). Uses the `fastmcp`
  package, not `mcp.server.fastmcp` — see "Deployment" below for why.
- `tools/` — one module per domain (`budgets`, `accounts`, `categories`,
  `payees`, `transactions`, `splits`, `bulk`, `months`, `budgeting`). Each exposes `register(mcp, client)`;
  `tools/__init__.py:register_all()` wires them all. Shared annotation dicts
  live in `tools/_common.py`. Transaction helpers shared by several modules
  (transfer resolution and rules, split validation, rendering) live in
  `tools/_txn.py`.

To add a tool: create/extend a module in `tools/`, define it inside `register()`
as a closure over `client`, and ensure the module is called from `register_all`.

## Conventions

- **Milliunits**: YNAB stores amounts in thousandths of a currency unit
  (12.50 => 12500). Tools accept/return normal currency units and convert.
  An **outflow (expense) is NEGATIVE**, an inflow (income) is POSITIVE.
- **budget_id**: `"last-used"` targets the most recently opened budget.
- **Rate limit**: 200 requests / hour / token. The API returns full collections;
  pagination in `list_*` tools is client-side via `paginate()`.
- **Transfers**: `payee_id` = the target account's `transfer_payee_id`; never a
  `"Transfer : X"` payee name. On-budget -> off-budget needs a category;
  on-budget -> on-budget has none (`tools/_txn.py:resolve_payee`).
- **Splits**: an existing split cannot be edited through the API; a non-split
  transaction is converted in place with `PUT` + `subtransactions`.
- Tool responses default to Markdown; pass `response_format="json"` for JSON.
- Every tool wraps its body in `try/except` and returns `handle_api_error(e)` —
  never let an exception escape to the client.
- Code, comments, and docstrings are in **English**.

## Environment variables

- `YNAB_TOKEN` (required) — YNAB Personal Access Token.
- `YNAB_BUDGET_ID` (optional) — default budget id for the tools.
- `MCP_TRANSPORT` — `stdio` (default) or `http` (streamable-http, endpoint `/mcp`).
- `HOST` / `PORT` — bind address for the `http` transport (default `0.0.0.0:8000`).
- `YNAB_TIMEOUT` — HTTP timeout in seconds (default `30`).

## Security

**Never commit `.env`** — it holds a live YNAB token and is gitignored. Use
`.env.example` as the template. If a token is ever exposed, rotate it in YNAB
(Account Settings → Developer Settings).

## Testing notes

Tests mock HTTP with `respx` and never hit the live API. `test_tools.py` drives
tools through `FastMCP.call_tool(name, args)`, which returns a `ToolResult`
whose `.structured_content["result"]` holds the tool's text output.

## Deployment (FastMCP Cloud)

The server depends on the `fastmcp` package (not the `mcp` SDK's built-in
`mcp.server.fastmcp`) specifically so it can be deployed as-is on
[FastMCP Cloud](https://fastmcp.cloud), which expects a `module:object`
entrypoint pointing at a `FastMCP` instance built with that package.

- Entrypoint: `src/ynab_mcp/server.py:mcp`.
- Dependencies are auto-detected from `pyproject.toml`.
- Set `YNAB_TOKEN` (and optionally `YNAB_BUDGET_ID`) as environment
  variables/secrets in the FastMCP Cloud project settings — never via `.env`,
  which isn't committed.
- Validate locally before pushing: `uv run fastmcp inspect src/ynab_mcp/server.py:mcp`.
- FastMCP Cloud runs its own HTTP transport; `MCP_TRANSPORT`/`HOST`/`PORT` only
  matter for `main()` (i.e. `uv run ynab-mcp` / Claude Desktop / self-hosting).
