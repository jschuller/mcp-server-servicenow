# Tools, resources and skills

19 tools, 5 resources and 5 Agent Skills. Every tool carries MCP annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`), so your client decides which calls need your approval. `--read-only` hides the 7 write tools, and so does an identity with `snc_read_only`.

## Tools

### Table API (6)
| Tool | Description |
|------|-------------|
| `list_records` | List records from any table with filtering, field selection and pagination; adds a `warning` when a requested field is missing from every row (it doesn't exist or an ACL hides it) |
| `get_record` | Get a single record by sys_id |
| `create_record` | Create a record in any table |
| `update_record` | Update a record |
| `delete_record` | Delete a record by sys_id |
| `aggregate_records` | COUNT, AVG, MIN, MAX, SUM with GROUP BY and HAVING via the Stats API |

### CMDB (5)
| Tool | Description |
|------|-------------|
| `list_ci` | List configuration items with class and query filtering |
| `get_ci` | Get a single CI by sys_id |
| `create_ci` | Create a configuration item |
| `update_ci` | Update a configuration item |
| `get_ci_relationships` | Parent/child relationships for a CI (paged: `limit`, `offset`) |

### System (3)
| Tool | Description |
|------|-------------|
| `get_system_properties` | Query system properties |
| `get_current_user` | The authenticated user: name, email, sys_id, roles |
| `get_table_schema` | Table data dictionary incl. inherited fields (`hierarchy`, per-field `defined_in`) |

### Update sets (5)
| Tool | Description |
|------|-------------|
| `list_update_sets` | List update sets with state filtering |
| `get_update_set` | Get update set details |
| `create_update_set` | Create an update set |
| `set_current_update_set` | Set your current update set |
| `list_update_set_changes` | List the changes inside an update set |

## Roles

ServiceNow's ACLs decide what the user can do; the server adds nothing on top. Base-system roles, from least to most (choosing an identity for a company instance: [recommended integration identity](configuration.md#recommended-integration-identity)):

| You want | Roles | Run with |
|---|---|---|
| Read ITSM and CMDB data (the [start-here](../README.md#2-create-an-integration-user) user) | `itil` + `snc_read_only` | no flag: write tools are hidden for `snc_read_only` |
| …and create or update incidents and CIs | `itil` (no `snc_read_only`) | no flag; the client asks before writes (`--read-only` on clients that don't ask) |
| …and delete incidents, problems, changes | add `itil_admin` | |
| Table schemas (`get_table_schema`, `servicenow://schema/*`) | add `personalize_dictionary` | |
| Update sets, system properties | `admin` — on a PDI only | |

| Tool or resource | Needs | Without it |
|---|---|---|
| `list_records`, `get_record`, `aggregate_records` | read access to that table (`itil` for task tables) | 403, or rows filtered out |
| `create_record`, `update_record` | write access to that table (`itil` for incidents) | 403 |
| `delete_record` | delete access (`itil_admin` for incidents) | 403 |
| `list_ci`, `get_ci`, `get_ci_relationships`, `servicenow://cmdb/classes` | `itil` or `cmdb_read` | 403, or rows filtered out |
| `create_ci`, `update_ci` | write access to the CI class | 403 |
| `get_table_schema`, `servicenow://schema/{table}` | `personalize_dictionary` | 403 naming the role |
| `get_system_properties` | `admin` | **an empty list, no error** |
| `get_current_user`, `servicenow://instance`, `servicenow://update-set/current` | any user | `instance` omits the platform version without `admin` |
| update-set tools | `admin` | 403 |

The reads, the empty `get_system_properties` and the 403s were checked live on a Brazil PDI on 2026-10-11 as `itil` + `snc_read_only`, and the record writes, schema and update-set tools as `admin`; the `itil` write, `itil_admin` delete and CI write rows follow ServiceNow's base-system role documentation. An instance with custom ACLs can differ — the error text names the API and method. API-key users also need a REST API access policy for each API they call (Table, Aggregate): see [TROUBLESHOOTING](../TROUBLESHOOTING.md#401-unauthorized).

## Resources

Read-only context a client can fetch without a tool call.

| Resource URI | Description |
|-------------|-------------|
| `servicenow://schema/{table_name}` | Field definitions (name, type, label, mandatory, reference, defined_in) for any table, parents included |
| `servicenow://instance` | Instance URL, platform version, logged-in user, timezone |
| `servicenow://update-set/current` | Current update set name, sys_id, state |
| `servicenow://cmdb/classes` | CMDB CI class hierarchy (names, labels, parent classes) |
| `servicenow://help/query-syntax` | Encoded query operators, including date ranges (the same file as `skill://exploring-tables/references/query-syntax.md`) |

## Skills (served over MCP)

Four [Agent Skills](https://agentskills.io) — guided, multi-step workflows that chain the tools above — ship inside the package and are served over MCP as resources, in the URI shape the MCP Skills Over MCP working group standardised in [SEP-2640](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2640). Every install gets them, on every client, with no plugin.

| Skill | URI | What it guides |
|-------|-----|----------------|
| **triaging-incidents** | `skill://triaging-incidents/SKILL.md` | List, triage, investigate and create incidents; trend reports that fall back to counting rows when aggregates are refused; SLA breaches |
| **servicenow-cmdb** | `skill://servicenow-cmdb/SKILL.md` | CI class hierarchy, dependency maps, CMDB health and full audits, data quality, CSDM taxonomy, CSDM 5 conformance by stage |
| **reviewing-update-sets** | `skill://reviewing-update-sets/SKILL.md` | Deep review, batch review, comparison and pre-promotion checks for update sets; preview problems and collisions of retrieved sets (admin) |
| **exploring-tables** | `skill://exploring-tables/SKILL.md` | Schema discovery (with a sampling fallback when the schema is refused), choice lists, data profiling, table search and comparison, the encoded-query reference |
| **analyzing-access** | `skill://analyzing-access/SKILL.md` | Who holds admin and security_admin, roles granted outside groups or left on inactive users, and what a 401, 403, empty result or missing field means |

Each skill states the tables it reads and the roles they need, in its text and in two frontmatter metadata keys (`io.github.jschuller/servicenow-roles`, `io.github.jschuller/servicenow-tables`). A 403 is reported as "not assessable with this identity"; 0 rows or missing fields as "possibly hidden by an ACL".

Each skill also exposes `skill://<name>/_manifest` (a JSON file list with SHA-256 digests, so a host can verify what it loaded) and its reference material as sibling resources, e.g. `skill://triaging-incidents/references/incident-fields.md`. Every read is an audit line. The server's `instructions` tell the model which skill matches which request; how each client picks them up is in [clients.md](clients.md#how-clients-use-the-skills).

## Safety rails

All off by default except the audit log; flags and environment variables are in [configuration.md](configuration.md#safety-rails).

- `--read-only` hides the write tools from `tools/list` **and** refuses any non-GET request at the HTTP layer. It is the only guarantee the server itself gives.
- When the identity holds `snc_read_only`, the write tools are hidden without any flag: ServiceNow would refuse them anyway, admin included. The server checks the caller's own `sys_user_has_role` rows once (5-second limit) for the configured account, or per token behind the OAuth proxy. This is a convenience, not a security control: if the check fails or times out, the write tools stay listed and ServiceNow refuses the write. One edge: `set_current_update_set` writes a `sys_user_preference` row, which `snc_read_only` may allow, but it is hidden with the other write tools.
- Table names, sys_ids, field lists and `order_by` are always validated; `javascript:` in caller queries is limited to `gs.*` date helpers unless `--allow-js-queries`.
- One JSON audit line per tool call or resource read (keys only, never values):

```json
{"ts":"2026-08-22T19:04:11.512+00:00","run_id":"…","event":"tool_call","name":"update_record","user":"admin","auth_mode":"service-account","transport":"stdio","table":"incident","sys_id":"9d385017c611228701d22104cc95c371","data_keys":["state"],"tags":["table","write"],"outcome":"ok","duration_ms":212.4}
```

**Who approves writes:** the MCP client. Claude Code and VS Code ask before a write tool unless you allowed it; Codex auto-runs only read-only tools; Antigravity asks before every MCP tool; opencode runs MCP tools without asking unless its `permission` config says `ask`, and pi has no approval prompts, so give those two `--read-only` or a read-only identity. ServiceNow's ACLs and `snc_read_only` remain the security boundary.
