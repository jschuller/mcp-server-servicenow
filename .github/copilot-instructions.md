# ServiceNow MCP Server — AI Coding Instructions

Python MCP server built with FastMCP 4.0. Exposes 19 tools + 5 resources for ServiceNow via the Model Context Protocol (speaks both the stateless 2026-07-28 revision and the legacy handshake).

## Source Code

- `src/servicenow_mcp/tools/` — Tool modules with `@mcp.tool()` decorators (table, CMDB, system, update sets)
- `src/servicenow_mcp/auth/` — Auth manager (basic, OAuth, API key) + OAuth proxy + token verifier
- `src/servicenow_mcp/utils/` — Pydantic config models, HTTP helper
- `src/servicenow_mcp/server.py` — FastMCP singleton, `make_sn_request()` helper
- `src/servicenow_mcp/cli.py` — CLI entry point with argparse

## Critical Patterns

1. **Tools use `@mcp.tool()` decorator** — Import `mcp` from `servicenow_mcp.server`. Use `Annotated[type, Field(description="...")]` for parameters.

2. **All API calls go through `make_sn_request()`** — Handles per-user OAuth tokens (proxy mode) vs global auth. Never call `requests.get()` directly.

3. **Config uses Pydantic BaseModel** — `ServerConfig`, `AuthConfig` in `utils/config.py`. CLI args and env vars resolved in `cli.py`.

4. **Auth manager handles token lifecycle** — `auth_manager.get_headers()` returns ready-to-use headers. OAuth tokens auto-refresh on 401.

5. **Responses use `parse_json_response()`** — From `utils/http.py`. Handles HTML login pages (hibernating instance) gracefully.

## Build & Test

```bash
pip install -e ".[dev]"
python -m pytest tests/ -v --ignore=tests/integration
ruff check src/ tests/
ruff format --check src/ tests/
```
