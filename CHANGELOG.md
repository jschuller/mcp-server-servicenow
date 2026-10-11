# Changelog

## [Unreleased] — 0.8.0

"One server, spec-native surface." The four ServiceNow skills stop being a
Claude-Code-plugin-only artifact and become part of the MCP contract: they ship
in the wheel and are served over MCP as `skill://` resources in the SEP-2640
URI shape (the Skills extension went Final on 2026-09-11). Every `pip`/`uvx`
install on every client gets the guided workflows. The server does not yet
declare the `io.modelcontextprotocol/skills` extension (`skills/list`), which
waits for FastMCP support. MCP prompts are deferred to 0.9.

Verified on 2026-10-10/11 against a Brazil instance with Claude Code 2.1.296,
VS Code 1.140 with GitHub Copilot, Codex CLI 0.162.1, opencode 1.19.0,
Antigravity CLI 1.1.20 and pi 1.1.0, and the write paths as an admin's own
OAuth token over Streamable HTTP — see "Verified clients" in
`docs/clients.md`.

### Upgrade notes
- **Breaking: `--write-confirm` / `SERVICENOW_WRITE_CONFIRM` are removed.** The
  server no longer starts with the flag; the environment variable is ignored.
  `update_record`, `update_ci` and `delete_record` lose their `confirm`
  argument. Approval of writes is the MCP client's job (tool annotations),
  with ServiceNow's ACLs and `snc_read_only` as the boundary.
- **Breaking: the table allow/deny lists are removed.** `--table-allowlist`
  and `--table-denylist` no longer exist (the server won't start with them),
  and `SERVICENOW_TABLE_ALLOWLIST` / `SERVICENOW_TABLE_DENYLIST` are ignored.
  They were a targeting guard, not a data boundary: with `sys_user*` denied, a
  live `incident` read with `fields=caller_id.email` still returned user data
  through the dot-walk. Scope tables and APIs on the instance instead, where
  ServiceNow enforces it for every client: ACLs and roles on the integration
  user, Machine Identity access controls and REST API access policies
  ([Security Best Practices Guide](https://www.servicenow.com/content/dam/servicenow-assets/public/en-us/doc-type/resource-center/white-paper/instance-security-best-practice.pdf),
  Australia, pp. 17 and 37). Identifier, field-list and `javascript:`
  validation stay.
- **The API-key header defaults to `x-sn-apikey`**, ServiceNow's default
  auth parameter (was `X-ServiceNow-API-Key`, which worked only where an
  admin had created a custom parameter by that name). If yours did, set
  `SERVICENOW_API_KEY_HEADER=X-ServiceNow-API-Key`.
- **Breaking (Claude Code plugin):** the four `/servicenow:*` slash commands
  are now the skills' own commands — `/servicenow:triage` →
  `/servicenow:triaging-incidents`, `/servicenow:cmdb` →
  `/servicenow:servicenow-cmdb`, `/servicenow:explore-table` →
  `/servicenow:exploring-tables`, `/servicenow:review-update-set` →
  `/servicenow:reviewing-update-sets`. The `servicenow-admin` subagent is
  removed (its audit, trend-report and batch-review patterns live in the
  skills). The skills no longer carry `allowed-tools`, so Claude Code may now
  ask before the MCP tools a skill uses.
- **`get_current_user` returns one shape for every auth type:** `user_name`,
  `user_display_name`, `user_email`, `user_sys_id`, `roles`, plus any extra
  `fields` you ask for. Basic-auth callers previously got the raw UI-endpoint
  payload. `roles` is now a list of role names, not a comma-separated string.
- **Eleven new resources** appear in `resources/list` (per skill: `SKILL.md`,
  `_manifest` with SHA-256 digests, `references/*.md`): 15 instead of 4.
- **The server sends `instructions`** naming the skill URIs (~200 tokens).
- **Audit:** an unknown resource URI is classified `unknown_resource` (was
  `unknown_tool`).
- **FastMCP floor is 4.1.0**; Python 3.14 is supported.

### Added
- **`mcp-server-servicenow --check`**: a read-only connection diagnostic with
  the same flags and environment as the server. One line per check — the
  configuration it understood, whether the instance answered (DNS, TLS, a
  hibernating PDI), the identity and its direct roles, whether write tools
  are hidden, a Table API read, schema access (a 403 names
  `personalize_dictionary`) and the Aggregate API (an API key without an
  access policy for it is reported as a policy limit, as is the per-record
  GET behind `get_record`). Exit code 0 when
  authentication and a read work. It never prints a secret, so the output
  can go straight into a Q&A post.
- **OAuth client credentials grant** for headless use (CI, scheduled jobs,
  SSO-only instances): with `SERVICENOW_AUTH_TYPE=oauth` and no username or
  password, the server requests a client-credentials token (client id and
  secret in the form body) and acts as the OAuth client's application user.
  A username and password together keep the password grant; setting only one
  is a startup error. The startup log names the grant, a refresh falls back to
  a new grant of the same type, and audit lines read
  `oauth-client:<client_id>`. Instance setup: configuration.md.
- **Write tools are hidden when the identity holds `snc_read_only`**, without
  any flag: ServiceNow would refuse those writes anyway, admin included. One
  lookup of the caller's own `sys_user_has_role` rows (5-second limit) for the
  configured account, or an `sn_read_only` claim per token behind the OAuth
  proxy. A call to a hidden tool is refused with a clear message and audited
  as `denied`. It fails open — if the lookup fails or times out the tools stay
  listed and ServiceNow refuses the write — so it is a convenience, not a
  security control; `--read-only` remains the server-side guarantee.
- Skills served over MCP via FastMCP's `SkillsDirectoryProvider`
  (`src/servicenow_mcp/skills/`, package data).
- Server `instructions`, and `render_instructions(namespace)` for servers that
  mount this one: FastMCP does not forward a mounted server's instructions and
  rewrites its URIs (`skill://snow/…`), so a parent can pass
  `render_instructions("snow")` on. `tests/test_mount.py` pins that policy and
  audit still apply through a parent.
- CI: Python 3.14, and a check that the wheel carries the 4 skills.

### Fixed
- The `servicenow-cmdb` skill named CMDB Health tables that don't exist
  (`cmdb_health_audit`, `cmdb_health_rule`, `cmdb_health_kpi`; the instance
  answers 400). It now reads `cmdb_health_scorecard`, `cmdb_health_result`,
  `cmdb_health_metric` and the staleness and orphan rule tables, each checked
  live with a least-privilege identity, and falls back to the full audit when
  the CMDB Health jobs have not run.
- `servicenow://cmdb/classes` stopped silently at 200 rows; a base instance
  has 700+ `cmdb_ci*` classes. It now pages through them (up to 5,000) and
  says `truncated: true` if it ever stops at that bound.
- The instance URL is normalised at startup: surrounding spaces, a trailing
  slash, a missing `https://`, a bare instance name (`dev12345` →
  `https://dev12345.service-now.com`) and a pasted UI path or query are all
  accepted, and the startup log shows the URL used. A missing scheme used to
  fail only at the first tool call (`MissingSchema`), and a URL copied from
  the UI gave a misleading "hibernating PDI" error.
- `SERVICENOW_AUTH_TYPE` is optional in `server.json` (the server already
  defaulted to `basic`), and the registry description fits its 100-character
  limit again.
- `get_current_user`, `servicenow://instance` and the OAuth proxy's `roles`
  claim read the caller's direct, active roles from `sys_user_has_role`. They
  read `sys_user.roles`, which is empty for most users, so `roles` was `null`
  for every caller (seen live for an `itil` + `snc_read_only` API-key user).
  Inherited roles are left out; every lookup is filtered to the caller.
- `set_current_update_set` and `servicenow://update-set/current` touch only the
  caller's own `sys_user_preference` row. Before, an admin could overwrite
  another user's current update set, and the fallback created a blank-user row
  — which ServiceNow treats as the system-wide default for every user.
- An OAuth token response without `access_token` raised nothing and sent
  `Authorization: Bearer None`; it now fails with a clear error, and a refresh
  grant that does so falls back to the password grant (#12).
- The token-verification cache could grow past `max_cache_size`.
- Clearer refusals: a `sys_dictionary` 403 names the `personalize_dictionary`
  role that schemas need; an API-key 401 points at REST API access policies
  instead of "check your username/password".
- Error messages name the fix: a basic-auth 401 names the "Web service access
  only" / `snc_basic_auth_api_access` restriction; TLS failures (corporate
  proxies) and DNS failures (typos, reclaimed PDIs) no longer read as "instance
  asleep"; HTML and empty responses give the PDI wake URL; a 403 links the
  roles-per-tool table. Links are absolute so the model can pass them on.

### Changed
- Server instructions ask the model to treat record text as data, not
  instructions, and to tell the user when a record contains instructions aimed
  at it, even if it ignores them.
- Getting started now creates a least-privilege integration user (Web Service
  Access Only, `itil` + `snc_read_only`, `--read-only`) instead of connecting as
  `admin`, which new instances refuse for REST basic auth. A roles table maps
  tools to roles; examples use `mcp.integration`.
- README cut from 486 to about 200 lines: what you can ask, a four-step quick
  start (Windows, VS Code with a password prompt, Claude Desktop), an "if it
  doesn't work" table, tools, roles and safety in brief. Reference material
  moved to `docs/tools.md`, `docs/clients.md` (every client, the plugin,
  verified clients), `docs/native-mcp.md` (updated for ServiceNow's pre-built
  MCP servers) and `docs/architecture.md`; "From source" to
  `docs/deployment.md`; development to `CONTRIBUTING.md`. Links are absolute,
  so they work on PyPI. All client snippets use `mcp.integration` and
  `--read-only` and no password on a command line.
- TROUBLESHOOTING starts with a symptom table and covers DNS failures,
  corporate TLS inspection and `spawn uvx ENOENT`.
- Package metadata: a plain summary, keywords, classifiers and project URLs.
- Support routes: `SUPPORT.md`, GitHub Discussions forms (Q&A, Show and tell),
  and the issue chooser points questions to Discussions.
- Dependencies refreshed (mcp 2.3.0, PyJWT 2.15.1, urllib3 2.8.0, anyio
  4.15.1, httpx2 2.13.1), clearing the open Dependabot alerts except PyJWT #38,
  which has no fixed release yet.
- Live tests (`scripts/stdio_smoke.py`, `tests/integration/`) take credentials
  from the environment only; the smoke has a `readonly` profile that changes
  nothing and a `write` profile for writable instances.

### Removed
- `commands/` and `agents/servicenow-admin.md`.
- Opt-in write confirmation (`--write-confirm`, `confirm.py`, the `confirm`
  tool argument, the audit `confirm`/`round` fields and the
  `cancelled`/`confirmation_required` outcomes). Where clients could show it,
  it came after their own approval prompt; where they couldn't, the model
  could pass `confirm=true` itself. About 290 lines of source and 360 of tests
  and smoke checks.

## [0.7.0] - 2026-09-05

"Developer data plane, with guardrails." Closes the write-safety and
auditability gap identified in the Action Fabric gap analysis, fixes the
correctness bugs found during that diligence, and restates what this server is
for: the raw Table API / schema / aggregates / update-set loop that ServiceNow's
native MCP Server Console excludes by design.

### Upgrade notes
No default-path change breaks a documented client, but five behaviours differ
from 0.6.x:
- **`delete_record` returns a dict** (`{"deleted": true, "table", "sys_id"}`)
  instead of the sentence `"Record … deleted from …"`.
- **`get_table_schema` / `servicenow://schema/{table}` include inherited
  fields by default** — `incident` now shows its `task` columns. Output gains
  `hierarchy` and per-field `defined_in` (existing keys unchanged); `limit`
  defaults to 200 (max 1000). Pass `include_inherited=false` for the old
  direct-only behaviour. Expect 2–3× more fields and one extra ServiceNow call
  per parent table.
- **`javascript:` in caller-supplied queries is restricted** to GlideSystem date
  helpers (`gs.daysAgo*`, `gs.beginningOf*`, `gs.endOf*`, `gs.*AgoStart/End`,
  `gs.now*`). Everything the shipped skills and the query-syntax resource teach
  still works; `gs.getUserName()`, `GlideRecord`, `;` etc. are rejected with a
  message naming `--allow-js-queries` / `SERVICENOW_ALLOW_JS_QUERIES=true`.
- **A JSON audit line per call is written to stderr by default.** Claude Desktop
  shows it in `mcp-server-servicenow.log`; Claude Code only in debug logs.
  `--audit-log off` or `--audit-log /path/file.jsonl` to change.
- **`MCP_STATIC_TOKENS` now requires ServiceNow service-account credentials**
  (basic, api_key, or OAuth client credentials) and no longer forwards the
  static token to ServiceNow. In 0.6.x that mode 401'd on every call, so
  nothing that worked stops working — unless you had pasted a real ServiceNow
  bearer into `MCP_STATIC_TOKENS` as a workaround.
- `update_record`, `update_ci` and `delete_record` gain an inert
  `confirm: bool = false` argument (only consulted under `--write-confirm`).

### Added
- **Tool annotations** on all 19 tools (`readOnlyHint`, `destructiveHint`,
  `idempotentHint`, `openWorldHint`) so clients can apply their own permission
  policies; Claude Code shows them in `/mcp`.
- **`--read-only` / `SERVICENOW_READ_ONLY`** — hides the 7 write tools and, as
  defence in depth, refuses any non-GET request in `make_sn_request`.
- **Table allow/deny lists** (`--table-allowlist`, `--table-denylist`; exact or
  glob, deny wins) enforced by a `PolicyMiddleware` on `table_name`,
  `class_name`, the fixed-table tools and the schema resource.
- **Opt-in destructive-call confirmation** (`--write-confirm`): `update_record`,
  `update_ci`, `delete_record` show the record's current values and ask via
  MCP elicitation — `ctx.elicit()` on handshake-era connections (Claude Code,
  Cursor), the 2026-07-28 multi round-trip `InputRequiredResult` on modern
  ones. Decline is final; a synthetic cancel (Claude Desktop/Cowork) or a
  client without elicitation falls back to an explicit `confirm=true`.
- **JSON audit log** (`AuditMiddleware`): user, auth mode, transport, tool,
  table, sys_id, redacted query, data keys, tags, outcome, duration. Never
  stdout, never values.
- `get_table_schema(include_inherited=…)` and the schema resource walk
  `sys_db_object.super_class` (depth ≤ 10, per-table queries with a child-first
  budget, graceful fallback when `sys_db_object` is unreadable).
- `get_ci_relationships` gains `limit` (default 100, max 1000) and `offset`.
- CLI helpers treat empty and unexpanded `${VAR}` environment values as unset —
  the Claude Code plugin can now pass every option through with
  `${VAR:-default}` without crashing startup when a var is not set.
- `servicenow://cmdb/classes` returns `super_class` as the parent's name
  instead of a `{link, value}` reference.
- **`.claude-plugin/marketplace.json`** — the plugin is now actually
  installable: `claude plugin marketplace add jschuller/mcp-server-servicenow`
  then `claude plugin install servicenow@mcp-server-servicenow`. Deliberately
  carries no `version` field, so it does not become a sixth version string to
  keep in sync (marketplace entries validate against `plugin.json` only when
  they declare one).

### Security
- **Encoded-query hardening**: caller-supplied `query`/`having` reject
  arbitrary `javascript:`; table names, sys_ids, `relation_type`, `state`,
  `order_by` and field lists are validated; URL path segments are
  percent-encoded so `../` or `?sysparm_query=` in an identifier can no longer
  rewrite a request or bypass a denylist.
- Static MCP tokens are tagged `sn_auth: service-account` and never forwarded
  to ServiceNow as a bearer.
- **`mcp-publisher` is pinned and checksum-verified** in `publish-mcp.yml`
  (v1.8.1, SHA-256 from that release's `checksums.txt`). It previously came
  from `releases/latest` unverified while running in a job holding the OIDC
  token that authorizes publishing to the `io.github.jschuller/*` namespace —
  the one unpinned artifact in an otherwise SHA-pinned pipeline.

### Fixed
- HTTP + `MCP_STATIC_TOKENS` mode: the caller's MCP token was sent to
  ServiceNow as `Authorization: Bearer`, so every call failed 401 with a
  misleading "per-user OAuth token may be expired" message. The configured
  service account is now used (any credential type), and the startup error is
  explicit when it is missing.
- `.claude-plugin/plugin.json` had drifted to 0.6.0; CI's version check now
  covers it (five fields).
- `SECURITY.md` supported-versions table (was still 0.3.x); README skills path
  (`skills/`, shipped via the plugin).
- **README's plugin install command never existed.** It documented
  `claude plugin add --from <url>`; there is no `add` subcommand (the verbs are
  `install`, `marketplace`, `list`, `validate`, …), so the advertised plugin
  install has been broken since it was written. Replaced with the real
  marketplace flow, verified end to end.
- **README's HTTP "From Source" example could not start.** It passed only
  ServiceNow credentials, so the fail-closed guard rejected it with
  `refusing to start streamable-http listener without authentication`. Now
  shows `--mcp-static-tokens`, verified to serve 200 with a bearer and 401
  without.

### Changed
- **FastMCP 4.0 is stable** (4.0.0 landed 2026-08-31): pin `4.0.0b2` →
  `>=4.0.3,<5`. `uvx mcp-server-servicenow` no longer needs `--prerelease
  allow` — the flag is gone from the README, `.mcp.json.example`, the plugin
  manifest, `docs/configuration.md` and the release checklist (13 occurrences),
  together with the two workarounds that existed only to resolve a pre-release
  at depth 2: the redundant `fastmcp-slim[client,server]` direct dependency and
  `[tool.uv] prerelease = "allow"` (closes #8).
- `anyio` declared as a direct dependency (async write tools run ServiceNow
  I/O on a worker thread).
- README: "developer data plane that runs alongside the native MCP Server"
  positioning, corrected native comparison table (Zurich P9 / Australia P2,
  Table API excluded, not on PDIs/GCC, OAuth 2.0 via Machine Identity
  Console), new Safety & governance section.
- `server.json` lists every environment variable; `docs/configuration.md`,
  `docs/deployment.md`, `TROUBLESHOOTING.md`, `RELEASING.md` and
  `.env.example` cover the new flags.

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
