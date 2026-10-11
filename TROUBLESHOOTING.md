# Troubleshooting

## Reading Error Messages

Error messages from this MCP server include diagnostic context from ServiceNow's response — the response body and key headers (`X-Is-Logged-In`, `X-Transaction-ID`). This context often pinpoints the exact cause:

- **403 with `WebServicePolicyValidator`** → The table needs `ws_access=true` in its dictionary entry
- **403 with ACL reference** → The user lacks the required role or ACL for that operation
- **404 with table name** → The table doesn't exist
- **`Invalid table name '…'`** → The name contains characters other than letters, digits and `_` (typos with spaces or slashes are rejected before any request is made)
- **401 with `X-Is-Logged-In: false`** → Credentials are invalid (not just expired)

The `X-Transaction-ID` header can be given to a ServiceNow admin to look up the exact server-side log entry.

## Instance is hibernating
PDIs hibernate after inactivity. Wake it at [developer.servicenow.com](https://developer.servicenow.com) — click your instance and select "Wake Up". You'll get HTML login pages instead of JSON until it's awake.

## 401 Unauthorized
- **OAuth proxy: browser login succeeds but every MCP call returns `invalid_token`:** the SN OAuth app's Scope Restriction is "Securely scoped" (the Zurich+ default), which blocks Table API access. Set it to "Broadly scoped" in the Application Registry record, or add REST API Access Policies covering the Table/Stats APIs
- **Basic auth rejected with `"Required to provide Auth information"` even though the password is correct:** the instance enforces ServiceNow's basic-auth restriction (`glide.authenticate.basic_auth.restriction.enforce`, default on new PDIs since mid-2026). The `admin` role is **not** exempt. Basic auth passes only for Web Service Access Only users (the simplest fix: a dedicated integration user with that box ticked), users holding `snc_basic_auth_api_access`, or a valid MFA one-time code. Upgraded instances get a tracking period first; on its end date the platform switches enforcement on by itself (`…restriction.enforcement_date`), so basic auth that worked yesterday can stop. Or use OAuth, which is unaffected
- **Basic auth:** Verify username/password are correct, and that the user may use basic auth at all (previous bullet)
- **OAuth:** Ensure the OAuth Application Registry entry is active and the redirect URI matches. Try regenerating the client secret
- **Expired token:** OAuth tokens expire; the server retries once automatically, but if both attempts fail, check your credentials
- **API key (`--auth-type api_key`):** a key authenticates only where a REST API access policy maps its auth profile for that API, method and resource — the global policy cannot carry token auth. A policy for Table API GET does not cover `aggregate_records` (Aggregate API, `/now/stats`), writes (PATCH/POST/DELETE), or a resource it does not list (e.g. `/now/table/{tableName}/{sys_id}`). The 401 names the method; add a policy per API you need. ServiceNow's default API-key header is `x-sn-apikey` (`--api-key-header x-sn-apikey`)

## 403 Access Denied
The error message includes the ServiceNow response body, which typically names the specific policy or ACL that blocked access. Common causes:
- **`WebServicePolicyValidator`** — The table's `ws_access` property is not set to `true`. Fix: go to System Definition > Tables, find the table, check "Allow access to this table via web services"
- **Missing role** — The integration user needs the appropriate role (e.g., `itil` for incident, `cmdb_read` for CMDB). Check the error body for the specific role required
- **Cross-scope restriction** — If accessing a scoped app's table, ensure cross-scope privileges are configured
- **Least-privilege identities** — see [what each tool needs](README.md#what-each-tool-needs): `get_table_schema` and `servicenow://schema/*` need `personalize_dictionary` (the 403 says so); update-set tools need `admin`; deleting incidents needs `itil_admin`; `snc_read_only` refuses every write. `get_system_properties` without `admin` returns an empty list rather than a 403

## `Unknown tool: 'update_record'` (or any write tool)
The server is running with `--read-only` / `SERVICENOW_READ_ONLY=true`: the 7 write tools are hidden from `tools/list`, and a cached client that still calls one gets this error. Restart without the flag to write.

## `Table 'x' is blocked by SERVICENOW_TABLE_DENYLIST` / `not in SERVICENOW_TABLE_ALLOWLIST`
The operator restricted which tables this server may touch. The check applies to `table_name`, `class_name` (default `cmdb_ci`), the fixed-table tools (`get_current_user` → `sys_user`, `get_system_properties` → `sys_properties`, update-set tools → `sys_update_set`/`sys_update_xml`, `get_ci_relationships` → `cmdb_rel_ci`) and the `servicenow://schema/{table}` resource. Patterns are globs (`sys_user*`), case-insensitive; deny wins over allow.

## `Query rejected: unsafe javascript: expression`
Caller-supplied `query` / `having` values may only use GlideSystem date helpers (`javascript:gs.daysAgo(7)`, `gs.daysAgoStart(1)`, `gs.beginningOfToday()`, `gs.beginningOfLastWeek()`, `gs.monthsAgoStart(1)`, `gs.nowDateTime()` …). Anything else — `gs.getUserName()`, `gs.getUserID()`, `GlideRecord`, `;`, `new` — is refused, including when it follows a safe helper in the same query. Use the `RELATIVE*`, `MORETHAN`/`LESSTHAN`, `DATEPART` operators (see `servicenow://help/query-syntax`), or start the server with `--allow-js-queries` / `SERVICENOW_ALLOW_JS_QUERIES=true`. The server's own internal queries (for example the `gs.getUserName()` lookup behind `get_current_user`) are not affected.

## 403 on `sys_store_app` / `sys_plugins` even as admin
These tables fail API-level ACL validation over REST regardless of role. Use `v_plugin` (installed plugins), `sys_scope` (applications) or `sys_db_object` (tables) instead.

## Audit log noise in stdio clients
One JSON line per tool call goes to stderr by default (Claude Desktop: `~/Library/Logs/Claude/mcp-server-servicenow.log`; Claude Code: debug logs only). Use `--audit-log off` to silence it or `--audit-log /path/audit.jsonl` to write a file. Values are never logged — only field names and a redacted, 200-character query.

## `get_current_user` fields
Since 0.8.0 `get_current_user` reads the caller's `sys_user` row through the Table API for every auth type (basic, OAuth, API key), so the shape no longer depends on how you sign in: `user_name`, `user_display_name`, `user_email`, `user_sys_id`, `roles`, plus any extra columns passed in `fields`. An empty result means the caller cannot read its own `sys_user` row.
