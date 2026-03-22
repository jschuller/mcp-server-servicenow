# Changelog

## [Unreleased]

## [0.5.0] - 2026-03-22

### Added
- **5 MCP Resources** — read-only context for LLM clients, avoiding repeated tool calls:
  - `servicenow://schema/{table_name}` — field definitions (parameterized template)
  - `servicenow://instance` — instance URL, version, user, timezone
  - `servicenow://update-set/current` — active update set name/sys_id
  - `servicenow://cmdb/classes` — CI class hierarchy from sys_db_object
  - `servicenow://help/query-syntax` — encoded query operators reference (static markdown)
- `aggregate_records` tool — COUNT/AVG/MIN/MAX/SUM with GROUP BY + HAVING via Stats API (`/api/now/stats/`)
- `.env.test` support for integration tests (auto-loaded by dotenv, gitignored)
- 7 new integration smoke tests: aggregate_records (with/without group_by) + 5 resource read tests

### Fixed
- `aggregate_records` group_by return type — Stats API returns list, wrapped as `{"count": N, "groups": [...]}`
- `__init__.py` version synced with pyproject.toml (was stuck at 0.3.0)

## [0.4.0] - 2026-03-22

### Added
- **FastMCP 3.1.1 upgrade** — bumped from 2.13.2, zero test breakage
- **MultiAuth** — `--mcp-static-tokens` composes OAuth proxy + StaticTokenVerifier for CI/CD
- **Token verification caching** — SHA-256 keyed, 5min TTL, 1000 entry max with auto-eviction
- **HTTP connection pooling** — shared `httpx.AsyncClient` across ServiceNowProvider → TokenVerifier
- **Response size limiting** — `ResponseLimitingMiddleware` at 500KB
- **Tool tags** — all 18 tools tagged `read`/`write` + `table`/`cmdb`/`admin`/`updateset`
- 4 Claude Code skills: CMDB explorer, table explorer, update set reviewer, incident triage
- Claude Code plugin packaging with slash commands and servicenow-admin agent
- README redesign: Mermaid diagram, badges, copy-paste config snippets
- Community health files: CHANGELOG, SECURITY, CODE_OF_CONDUCT, PR template, copilot instructions
- Extracted docs: configuration.md, deployment.md, TROUBLESHOOTING.md

### Security
- Auth header leak prevention (automatic via fastmcp ≥3.0.2 floor)

## [0.3.1] - 2026-02-26

### Fixed
- CLI TypeError on stdio transport (`unexpected keyword argument 'host'`)
- server.json description length for MCP Registry (max 100 chars)

### Added
- MCP Registry schema and automated publish workflow
- `.mcp.json.example` and configuration examples in README

### Changed
- Renamed package to `mcp-server-servicenow`

## [0.3.0] - 2026-02-23

### Added
- OAuth 2.1 + PKCE proxy for per-user ServiceNow auth (Phase 3)
- FastMCP 3.0 migration with dual transport (Phase 2)
- Streamable HTTP transport and Cloud Run deployment
- Security model docs and native vs community comparison
- CI workflow, LICENSE, issue templates, integration tests

## [0.1.0] - 2026-02-07

### Added
- 18-tool ServiceNow MCP server (Phase 1)
- Table API, CMDB, System, Update Sets tool modules
- Basic auth, OAuth password grant, API key authentication
- Pydantic configuration, unit tests
