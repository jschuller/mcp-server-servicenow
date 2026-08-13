# Changelog

## [0.6.1] - 2026-08-13

### Added
- **mypy in CI** — the shipped `py.typed` marker is now backed by an actual
  type check: `mypy src/` runs between format check and tests, with
  `disallow_untyped_defs` across all first-party code and zero suppressions.
  One annotation corrected along the way (`_parse_static_tokens` claims dict
  is `dict[str, Any]`, not `dict[str, str]`) (#9)

### Fixed
- **ROPC OAuth (stdio path)**: the password-grant token request now honors the
  configured `--timeout` instead of hanging indefinitely on an unresponsive
  instance, and the `refresh_token` from the token response is stored and
  used — `refresh_token()` performs a real `grant_type=refresh_token`
  exchange (rotation-aware) and falls back to the password grant only when
  the refresh grant is rejected or errors. New `tests/test_auth_manager.py`
  covers both behaviors (11 tests) (#7)
- Documented that uv/uvx installs need `--prerelease allow` while the FastMCP
  4.0 beta pin is in place (uv only honors pre-release markers in the user's
  own top-level requirement; pip is unaffected). All uvx examples and the
  plugin manifest now carry the flag.

### Changed
- Dependency refresh (Dependabot #6): requests 2.33.0, cryptography 50.0.0,
  pytest 9.0.3, pydantic-settings 2.14.2, pyjwt 2.13.0, urllib3 2.7.0
- Declined community PR #10 (premature FastMCP `>=4.0.0` bump — no stable
  4.0 exists on PyPI yet); #8 remains the tracking issue for the un-pin

## [0.6.0] - 2026-08-12

### Added
- **OAuth 2.1 + PKCE validated end-to-end** on a Zurich PDI: DCR → consent →
  SN login (SSO/MFA-compatible) → ephemeral-loopback callback → per-user tool
  calls. Two Zurich gotchas documented: new PDIs require the
  `snc_basic_auth_api_access` role for REST basic auth, and new OAuth apps
  default to "Securely scoped" tokens which reject Table API calls
- **FastMCP 4.0 (MCP 2026-07-28 protocol)** — the server now speaks both the
  stateless 2026-07-28 MCP revision and the legacy handshake protocol,
  negotiated per connection. Existing stdio clients are unaffected.
  (`fastmcp==4.0.0b2`, exact pin while 4.0 is in beta; `httpx` → `httpx2`,
  pydantic floor 2.12)
- `tests/test_cli.py` — first coverage for the CLI: fail-closed startup,
  static-token/OAuth wiring, arg parsing (18 tests)
- Python 3.13 in the CI matrix and package classifiers
- CI enforces `ruff format --check`; lint rule set pinned in pyproject so
  unpinned ruff upgrades can't break CI
- `uv.lock` is now committed

### Security
- **Fail closed on HTTP**: a non-stdio listener refuses to start unless MCP
  endpoint auth (`MCP_OAUTH_*` or `MCP_STATIC_TOKENS`) is configured
- **Bind localhost by default**: `--host` defaults to `127.0.0.1`; all-interface
  binding is opt-in via `MCP_HOST=0.0.0.0` (the Docker image sets this — the
  container boundary is the isolation)
- PyPI publishing via Trusted Publishing (OIDC), GitHub Actions pinned to
  commit SHAs, broadened `.gitignore` secret patterns, Renovate enabled

### Fixed
- `list_records` `order_by` descending: a leading `-` now emits `ORDERBYDESC`
  instead of being silently discarded by ServiceNow — thanks @Nono-04 (#5,
  fixes #3 reported by @MMunManAIDev)
- Docker image: startup regression from the fail-closed hardening (missing
  MCP auth guidance + loopback binding inside the container)
- MCP server identity now reports the package version instead of FastMCP's
- `aggregate_records` was missing from the plugin agent/command allow-lists,
  making the Stats API tool unreachable from `/servicenow:*` commands
- Plugin manifest version was stuck at 0.4.0
- `server.json`: PKCE requires San Diego+ (2022); Tokyo+ applies to the
  Table API tools, not OAuth

### Changed
- Dropped direct `authlib`/`cryptography` dependencies (never imported;
  FastMCP brings what it needs transitively)

## [0.5.1] - 2026-03-22

### Fixed
- Added MCP Registry ownership tag (`mcp-name`) to README for registry validation
- Pre-publish polish: ruff format (17 files), sdist excludes (960KB → 27KB), PyPI image URL fix, keywords

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

### Improved
- **Enriched error responses** — 401/403/404 errors now include ServiceNow response body (500 char preview) and diagnostic headers (`X-Is-Logged-In`, `X-Transaction-ID`). Pinpoints exact cause (e.g., `WebServicePolicyValidator`, missing ACL, wrong table name).
- Expanded TROUBLESHOOTING.md with error message interpretation guide

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
