# Troubleshooting

Start with `mcp-server-servicenow --check` (or `uvx mcp-server-servicenow --check`) using the same environment variables and flags as your client config. It makes read-only requests and prints one line per check: the configuration it understood (instance URL after normalisation, auth type and grant, flags), whether the instance answered, the identity and its roles, whether write tools are hidden, a Table API read, schema access and the Aggregate API. It exits 0 when authentication and a read work. It never prints a password, key or token, so you can paste the output into a question.

| You see | Likely cause | Fix |
|---|---|---|
| `Got HTML instead of JSON`, or an empty response | The PDI is hibernating, or a login page answered | [Wake the instance](#instance-is-hibernating) |
| `401` with `Required to provide Auth information` | The basic-auth restriction: the user is not *Web service access only* | [401 Unauthorized](#401-unauthorized) |
| `403 Access denied` | The user lacks a role or an ACL | [403](#403-access-denied), [roles per tool](docs/tools.md#roles) |
| `Cannot resolve the host` | A typo in the URL, or a reclaimed PDI | [Instance not found](#instance-not-found) |
| `TLS certificate check failed` / `certificate verify failed` | A corporate proxy inspects TLS | [Certificates](#certificate-verify-failed) |
| `spawn uvx ENOENT` | The client cannot find `uvx` | [spawn uvx ENOENT](#spawn-uvx-enoent) |
| `Unknown tool: 'update_record'`, or `identity has snc_read_only; write tools are hidden` | The server runs with `--read-only`, or the identity is read-only | [Read-only](#unknown-tool-update_record-or-any-write-tool) |

## Reading Error Messages

Error messages from this MCP server include diagnostic context from ServiceNow's response — the response body and key headers (`X-Is-Logged-In`, `X-Transaction-ID`). This context often pinpoints the exact cause:

- **403 with `WebServicePolicyValidator`** → The table needs `ws_access=true` in its dictionary entry
- **403 with ACL reference** → The user lacks the required role or ACL for that operation
- **404** → The table or record doesn't exist, or an ACL hides the record from this identity: a record the user may not read answers 404, not 403
- **`Invalid table name '…'`** → The name contains characters other than letters, digits and `_` (typos with spaces or slashes are rejected before any request is made)
- **401 with `X-Is-Logged-In: false`** → Credentials are invalid (not just expired)

The `X-Transaction-ID` header can be given to a ServiceNow admin to look up the exact server-side log entry.

## Instance is hibernating
PDIs hibernate after inactivity. Wake it at [developer.servicenow.com](https://developer.servicenow.com/dev.do#!/home?wu=true) — sign in and the instance wakes, or click your instance and select "Wake Up". You'll get HTML login pages instead of JSON until it's awake.

## Instance not found
`Cannot resolve the host` means DNS has no answer for the instance name. Check the URL (`https://devNNNNNN.service-now.com`, no path after the host). A PDI left unused for about ten days is reclaimed and its name stops resolving: request a new one from the developer portal.

## `certificate verify failed`
A corporate proxy that inspects TLS presents its own certificate, which Python does not trust by default. Point `REQUESTS_CA_BUNDLE` at your company's CA bundle in the server's environment (the `env` block of your client config). If `uvx` itself fails to download the package for the same reason, set `UV_SYSTEM_CERTS=true` (or `SSL_CERT_FILE`) so uv uses the system store. Where uv is blocked by policy, `pipx run mcp-server-servicenow` or `pip install mcp-server-servicenow` work too.

## `spawn uvx ENOENT`
Desktop apps (Claude Desktop, some IDEs) do not inherit your shell's `PATH`, so they cannot find `uvx`. Use the full path as the `command`: `which uvx` on macOS/Linux, `where uvx` on Windows.

## 401 Unauthorized
- **OAuth proxy: browser login succeeds but every MCP call returns `invalid_token`:** the SN OAuth app's Scope Restriction is "Securely scoped" (the Zurich+ default), which blocks Table API access. Set it to "Broadly scoped" in the Application Registry record, or add REST API Access Policies covering the Table/Stats APIs
- **Basic auth rejected with `"Required to provide Auth information"` even though the password is correct:** the instance enforces ServiceNow's basic-auth restriction (`glide.authenticate.basic_auth.restriction.enforce`, default on new PDIs since mid-2026). The `admin` role is **not** exempt. Basic auth passes only for Web Service Access Only users (the simplest fix: a dedicated integration user with that box ticked), users holding `snc_basic_auth_api_access`, or a valid MFA one-time code. Upgraded instances get a tracking period first; on its end date the platform switches enforcement on by itself (`…restriction.enforcement_date`), so basic auth that worked yesterday can stop. Or use OAuth, which is unaffected
- **Basic auth:** Verify username/password are correct, and that the user may use basic auth at all (previous bullet)
- **OAuth:** Ensure the OAuth Application Registry entry is active and the redirect URI matches. Try regenerating the client secret
- **Expired token:** OAuth tokens expire; the server retries once automatically, but if both attempts fail, check your credentials
- **API key (`--auth-type api_key`):** a key authenticates only where a REST API access policy maps its auth profile for that API, method and resource — the global policy cannot carry token auth. A policy for Table API GET does not cover `aggregate_records` (Aggregate API, `/now/stats`), writes (PATCH/POST/DELETE), or a resource it does not list (e.g. `/now/table/{tableName}/{sys_id}`). The 401 names the method; add a policy per API you need. The server sends the key in `x-sn-apikey`, ServiceNow's default auth parameter; if your admin created a custom header parameter, set `SERVICENOW_API_KEY_HEADER` to its name

## 403 Access Denied
The error message includes the ServiceNow response body, which typically names the specific policy or ACL that blocked access. Common causes:
- **`WebServicePolicyValidator`** — The table's `ws_access` property is not set to `true`. Fix: go to System Definition > Tables, find the table, check "Allow access to this table via web services"
- **Missing role** — The integration user needs the appropriate role (e.g., `itil` for incident, `cmdb_read` for CMDB). Check the error body for the specific role required
- **Cross-scope restriction** — If accessing a scoped app's table, ensure cross-scope privileges are configured
- **Least-privilege identities** — see [roles per tool](docs/tools.md#roles): `get_table_schema` and `servicenow://schema/*` need `personalize_dictionary` (the 403 says so); update-set tools need `admin`; deleting incidents needs `itil_admin`; `snc_read_only` refuses every write. `get_system_properties` without `admin` returns an empty list rather than a 403

## `Unknown tool: 'update_record'` (or any write tool)
The server is running with `--read-only` / `SERVICENOW_READ_ONLY=true`: the 7 write tools are hidden from `tools/list`, and a cached client that still calls one gets this error. Restart without the flag to write.

`identity has snc_read_only; write tools are hidden` means the ServiceNow user holds `snc_read_only`, which blocks every write regardless of its other roles, so the server hides the write tools too. To write, use an identity without `snc_read_only` (see [roles](docs/tools.md#roles)).

## `Query rejected: unsafe javascript: expression`
Caller-supplied `query` / `having` values may only use GlideSystem date helpers (`javascript:gs.daysAgo(7)`, `gs.daysAgoStart(1)`, `gs.beginningOfToday()`, `gs.beginningOfLastWeek()`, `gs.monthsAgoStart(1)`, `gs.nowDateTime()` …), and `gs.dateGenerate()` with a literal date, as in the list UI's `ON`/`BETWEEN` ranges. Anything else — `gs.getUserName()`, `gs.getUserID()`, `GlideRecord`, `;`, `new` — is refused, including when it follows a safe helper in the same query. Use the `RELATIVE*` operators or `ON`/`BETWEEN` ranges (see `servicenow://help/query-syntax`, served while the skills are on), or start the server with `--allow-js-queries` / `SERVICENOW_ALLOW_JS_QUERIES=true`. The server's own internal queries (for example the `gs.getUserName()` lookup behind `get_current_user`) are not affected.

## Warning: `…which no row carries: the instance ignored this condition`
The Table API drops a condition on a field that the table doesn't have, and often one on a field an ACL hides, instead of refusing the query. The "filtered" rows are then unfiltered. `list_records` and `list_ci` check the fields named in `query=` against the rows that come back and name the ones no row carries. Example: on a Brazil instance whose incident table has no `problem_id` field, `active=true^problem_idISNOTEMPTY` returned all 40 active incidents, and the warning named `problem_id`. To fix the query, find the real column name with `get_table_schema` (needs `personalize_dictionary`), or read one row without `fields=` to see the readable columns. A field defined on a table that extends the one you query (a CMDB subclass such as `cmdb_ci_service`, or a task type) comes back only when you query that table. If the field exists, an ACL hides it from this identity, and the filter can't be applied with it.

## Warning: `0 rows … not assessable here, not empty` (journal) or `0 rows may mean this identity can't read sys_audit rows` (audit)
Work notes, comments and field changes live in `sys_journal_field` and `sys_audit`, which need `admin` or `audit_viewer`. Without them the journal answers with 0 rows rather than a 403, so "no history" and "not allowed to see it" look the same; `list_records` adds this warning. The record's own journal fields still show the entries: `list_records` on the record's table with `query="sys_id=<sys_id>"`, `fields="work_notes,comments"` and `display_value="true"`. Field changes need `admin` or `audit_viewer` too (without them `sys_audit` usually answers 403). If `sys_audit` returns 0 rows with the warning instead, no field changes are visible to this identity: that is not the same as none.

## 403 on `sys_store_app` / `sys_plugins` even as admin
These tables fail API-level ACL validation over REST regardless of role. Use `v_plugin` (installed plugins), `sys_scope` (applications) or `sys_db_object` (tables) instead.

## Audit log noise in stdio clients
One JSON line per tool call goes to stderr by default (Claude Desktop: `~/Library/Logs/Claude/mcp-server-servicenow.log`; Claude Code: debug logs only). Use `--audit-log off` to silence it or `--audit-log /path/audit.jsonl` to write a file. Written field values are never logged, only their names. The encoded query is logged (password-, secret- and token-like values masked, 200 characters at most), so it can hold filter values such as names or email addresses; turn the log off or keep the file private if that matters.

## `get_current_user` fields
Since 0.8.0 `get_current_user` reads the caller's `sys_user` row through the Table API for every auth type (basic, OAuth, API key), so the shape no longer depends on how you sign in: `user_name`, `user_display_name`, `user_email`, `user_sys_id`, `roles`, plus any extra columns passed in `fields`. `roles` lists the caller's directly assigned, active roles from `sys_user_has_role` (roles inherited through other roles or groups are left out); it is `null` when the caller cannot read its own role rows. An empty result means the caller cannot read its own `sys_user` row.
