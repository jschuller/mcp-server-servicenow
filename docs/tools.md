# Tools, resources and skills

20 tools, 5 resources and 4 Agent Skills. The tables below are written for people; [What the model sees](#what-the-model-sees-generated) at the end is generated from the server and lists the descriptions and parameters a client actually receives. Every tool carries MCP annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`), so your client decides which calls need your approval. `--read-only` hides the 7 write tools, and so does an identity with `snc_read_only`.

The list tools (`list_records`, `list_ci`, `get_ci_relationships`, `get_system_properties`, `list_update_sets`, `list_update_set_changes`, `get_table_schema`, `find_references`) publish an `outputSchema` and return `structuredContent` next to the same JSON as text. A result over the 500 KB limit keeps that shape: it holds the first rows that fit and says `"truncated": true`, plus `next_offset` for the tools that take `offset`. Other tools are cut to text at the limit.

## Tools

### Table API (6)
| Tool | Description |
|------|-------------|
| `list_records` | List records from any table with filtering, field selection and pagination. Adds a `warning` when a requested field is missing from every row (it doesn't exist or an ACL hides it), and when `query=` filters on such a field or on a term that starts with an uppercase letter (a label like `Name`; columns are lowercase): the instance ignores those conditions, so the rows may be unfiltered (a dot-walk can also be missing because only the referenced records are unreadable). The fields in `query=` are checked without adding them to the returned rows; a dot-walk in `query=` is checked whole only when `fields=` is given, and at most 50 query fields are checked. Such terms are counted, never quoted, and a term the server can't parse, or a misspelled operator (`name Like x`), is not detected; field names are echoed in field-name characters only. `response_format="concise"` returns reference fields as bare sys_ids, without their instance links. `display_value="true"` returns labels in place of sys_ids and choice values, `"all"` returns `{display_value, value}` per field, and a `display_note` says that display dates are in this identity's time zone while stored values are UTC. 0 rows from `sys_journal_field` or `sys_audit` add a `warning` unless the identity visibly holds `admin` or `audit_viewer`: the instance can hide those rows instead of refusing |
| `get_record` | Get a single record by sys_id. Takes `display_value` like `list_records` |
| `create_record` | Create a record in any table |
| `update_record` | Update a record |
| `delete_record` | Delete a record by sys_id |
| `aggregate_records` | COUNT, AVG, MIN, MAX, SUM with GROUP BY and HAVING via the Stats API. `display_value="true"` returns group-by labels in place of sys_ids and choice values, `"all"` returns both. `having` takes `aggregate^field^operator^value`, such as `count^name^>^1` |

### CMDB (5)
| Tool | Description |
|------|-------------|
| `list_ci` | List configuration items with class and query filtering. Takes `response_format` and `display_value`, and adds the same `warning` and `display_note`, like `list_records` |
| `get_ci` | Get a single CI by sys_id. Takes `display_value` like `list_records` |
| `create_ci` | Create a configuration item |
| `update_ci` | Update a configuration item |
| `get_ci_relationships` | Parent/child relationships for a CI (paged: `limit`, `offset`) |

### System (4)
| Tool | Description |
|------|-------------|
| `get_system_properties` | Query system properties |
| `get_current_user` | The authenticated user: name, email, sys_id, roles |
| `get_table_schema` | Table data dictionary incl. inherited fields (`hierarchy`, per-field `defined_in`) |
| `find_references` | Where-used for a table or one field: business rules, client scripts, UI policies (or their field actions), ACLs, script includes (text match) and reference fields. Names, sys_ids and flags only, never script or ACL bodies; a source this identity can't read is listed in `not_assessable` |

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
| A record's work notes, comments and field changes (exploring-tables workflow 6) | add `audit_viewer` | without it the journal returns 0 rows, not a 403 |
| Where-used (`find_references`) | `admin` (`security_admin` for ACLs) | each source refused with 403, or with 401 by an access policy that leaves its table out, is listed in `not_assessable`; under basic auth the first 401 is an error |
| Update sets, system properties | `admin` — on a PDI only | |

| Tool or resource | Needs | Without it |
|---|---|---|
| `list_records`, `get_record`, `aggregate_records` | read access to that table (`itil` for task tables) | 403, or rows filtered out |
| `create_record`, `update_record` | write access to that table (`itil` for incidents) | 403 |
| `delete_record` | delete access (`itil_admin` for incidents) | 403 |
| `list_ci`, `get_ci`, `get_ci_relationships`, `servicenow://cmdb/classes` | `itil` or `cmdb_read` | 403, or rows filtered out |
| `create_ci`, `update_ci` | write access to the CI class | 403 |
| `get_table_schema`, `servicenow://schema/{table}` | `personalize_dictionary` | 403 naming the role |
| `find_references` | `admin`, or read access to `sys_script`, `sys_script_client`, `sys_ui_policy`, `sys_ui_policy_action`, `sys_security_acl` (`security_admin`), `sys_script_include` and `sys_dictionary` | that source in `not_assessable`; the others still answer |
| `get_system_properties` | `admin` | **an empty list, no error** |
| `get_current_user`, `servicenow://instance`, `servicenow://update-set/current` | any user | without `admin`, `instance` has no build or default time zone: `unavailable` names each and why |
| update-set tools | `admin` | 403 |

The reads, the empty `get_system_properties` and the 403s were checked live on a Brazil PDI on 2026-10-11 as `itil` + `snc_read_only`, and the record writes, schema and update-set tools as `admin`; the `itil` write, `itil_admin` delete and CI write rows follow ServiceNow's base-system role documentation. An instance with custom ACLs can differ — the error text names the API and method. API-key users also need a REST API access policy for each API they call (Table, Aggregate): see [TROUBLESHOOTING](../TROUBLESHOOTING.md#401-unauthorized).

## Resources

Read-only context a client can fetch without a tool call.

| Resource URI | Description |
|-------------|-------------|
| `servicenow://schema/{table_name}` | Field definitions (name, type, label, mandatory, reference, defined_in) for any table, parents included |
| `servicenow://instance` | Instance URL, build (`glide.war`) and release family, default time zone, and the logged-in user with roles and time zone; `unavailable` names each value this identity can't read, and why |
| `servicenow://update-set/current` | Current update set name, sys_id, state |
| `servicenow://cmdb/classes` | CMDB CI class hierarchy (names, labels, parent classes) |
| `servicenow://help/query-syntax` | Encoded query operators, including date ranges (the same file as `skill://exploring-tables/references/query-syntax.md`, so not served with `SERVICENOW_SKILLS=off`) |

## Skills (served over MCP)

Four [Agent Skills](https://agentskills.io) for the Now Platform — guided, multi-step workflows that chain the tools above — ship inside the package and are served over MCP as resources, in the URI shape the MCP Skills Over MCP working group standardised in [SEP-2640](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2640). Every install gets them, on every client, with no plugin.

| Skill | URI | What it guides |
|-------|-----|----------------|
| **servicenow-cmdb** | `skill://servicenow-cmdb/SKILL.md` | The CMDB as a data model: class hierarchy, raw relationships, health scorecards, data quality (duplicates, orphans, staleness, missing fields, locations, models and assets), CSDM taxonomy, CSDM 5 conformance by stage |
| **reviewing-update-sets** | `skill://reviewing-update-sets/SKILL.md` | Deep review, batch review, comparison and pre-promotion checks for update sets; preview problems and collisions of retrieved sets (admin) |
| **exploring-tables** | `skill://exploring-tables/SKILL.md` | Schema discovery (with a sampling fallback when the schema is refused), choice lists, data profiling, table search and comparison, a record's journal and audit history, where-used for a table or field (`find_references`), the encoded-query reference |
| **analyzing-access** | `skill://analyzing-access/SKILL.md` | Who holds admin and security_admin, roles granted outside groups or left on inactive users, team rosters and group members, and what a 401, 403, empty result or missing field means |

Each skill states the tables it reads and the roles they need, in its text and in two frontmatter metadata keys (`io.github.jschuller/servicenow-roles`, `io.github.jschuller/servicenow-tables`). A 403 is reported as "not assessable with this identity"; 0 rows or missing fields as "possibly hidden by an ACL".

Application skills, such as incident triage (ITSM), live outside the package: the one that shipped here until 0.9.0 is now [`examples/incident-triage`](../examples/incident-triage/), and [EXTENDING.md](../EXTENDING.md) covers writing your own.

Each skill also exposes `skill://<name>/_manifest` (a JSON file list with SHA-256 digests, so a host can verify what it loaded) and its reference material as sibling resources, e.g. `skill://analyzing-access/references/access-errors.md`. Every read is an audit line. The server's `instructions` tell the model which skill matches which request; how each client picks them up is in [clients.md](clients.md#how-clients-use-the-skills).

`SERVICENOW_SKILLS=off` (`--skills off`) serves none of them, nor the query-syntax alias, and leaves the skill list out of the instructions; the query, access and record-text guidance in the instructions stays. Skills a client loads from disk, such as the Claude Code plugin's copy, are not affected ([configuration](configuration.md#skills)).

## Safety rails

All off by default except the audit log; flags and environment variables are in [configuration.md](configuration.md#safety-rails).

- `--read-only` hides the write tools from `tools/list` **and** refuses any non-GET request at the HTTP layer. It is the only guarantee the server itself gives.
- When the identity holds `snc_read_only`, the write tools are hidden without any flag: ServiceNow would refuse them anyway, admin included. The server checks the caller's own `sys_user_has_role` rows once (5-second limit) for the configured account, or per token behind the OAuth proxy. This is a convenience, not a security control: if the check fails or times out, the write tools stay listed and ServiceNow refuses the write. One edge: `set_current_update_set` writes a `sys_user_preference` row, which `snc_read_only` may allow, but it is hidden with the other write tools.
- Table names, sys_ids, field lists and `order_by` are always validated; `javascript:` in caller queries is limited to `gs.*` date helpers unless `--allow-js-queries`.
- One JSON audit line per tool call or resource read. Written field values are never logged, only their names (`data_keys`); the encoded query is logged with password-, secret- and token-like values masked, so it can hold filter values such as names or emails:

```json
{"ts":"2026-08-22T19:04:11.512+00:00","run_id":"…","event":"tool_call","name":"update_record","user":"admin","auth_mode":"service-account","transport":"stdio","table":"incident","sys_id":"9d385017c611228701d22104cc95c371","data_keys":["state"],"tags":["table","write"],"outcome":"ok","duration_ms":212.4}
```

**Who approves writes:** the MCP client. Claude Code and VS Code ask before a write tool unless you allowed it; Codex auto-runs only read-only tools; Antigravity asks before every MCP tool; opencode runs MCP tools without asking unless its `permission` config says `ask`, and pi has no approval prompts, so give those two `--read-only` or a read-only identity. ServiceNow's ACLs and `snc_read_only` remain the security boundary.

## What the model sees (generated)

<!-- BEGIN GENERATED by scripts/contract.py: do not edit by hand -->

Read from the server itself with the default settings (skills on, write tools served) by `scripts/contract.py`. The descriptions are the ones the model reads; the tables above are written for people. The full contract, with input and output schemas, annotations, resources and the server instructions, is [contract.json](contract.json). Tests fail when either drifts from the code: `uv run --frozen --extra dev python scripts/contract.py --write` regenerates both.

| Tool | Kind | Parameters (**required**) | Structured output | Description the model reads |
|---|---|---|---|---|
| `aggregate_records` | read | **table_name**: string · count: boolean = true · avg_fields: string · min_fields: string · max_fields: string · sum_fields: string · group_by: string · query: string · having: string · display_value: "false" \| "true" \| "all" = "false" | no | Aggregate records using COUNT, AVG, MIN, MAX, SUM with optional GROUP BY via the Stats API. If the Stats API is refused (401) while list_records works, count with list_records instead: the same query, fields="sys_id", limit=1000, paging with offset. |
| `create_ci` | write | **data**: object · class_name: string = "cmdb_ci" | no | Create a new CMDB configuration item |
| `create_record` | write | **table_name**: string · **data**: object | no | Create a new record in any ServiceNow table |
| `create_update_set` | write | **name**: string · description: string · parent: string | no | Create a new update set for tracking customizations |
| `delete_record` | write, destructive | **table_name**: string · **sys_id**: string | no | Delete a record from a ServiceNow table by sys_id |
| `find_references` | read | **table_name**: string · field_name: string · limit: integer = 50 | yes | Where-used for a table or one of its fields: the business rules, client scripts, UI policies, ACLs, script includes and reference fields that touch it. Returns names, sys_ids and flags only, never script, condition or ACL bodies. Script matches (script includes; business rules and client scripts in field mode) are text matches, so expect false positives. Only this exact table is matched: run it again for a parent table (get_table_schema's hierarchy) to find rules and ACLs defined there. A source this identity can't read (403, or a 401 from an access policy that leaves its table out) is listed in not_assessable (under OAuth each such source costs one token refresh). Under basic auth the first 401 is an error (a refused password looks the same), and so is a refused OAuth secret; rows hidden by an ACL are simply missing. complete=false means the source hit the limit. |
| `get_ci` | read | **sys_id**: string · class_name: string = "cmdb_ci" · display_value: "false" \| "true" \| "all" = "false" | no | Get a single CMDB configuration item by sys_id |
| `get_ci_relationships` | read | **sys_id**: string · relation_type: string · limit: integer = 100 · offset: integer = 0 | yes | Get relationships for a CMDB configuration item (parent and child) |
| `get_current_user` | read | fields: string | no | Get the authenticated user's identity and directly assigned, active roles |
| `get_record` | read | **table_name**: string · **sys_id**: string · fields: string · display_value: "false" \| "true" \| "all" = "false" | no | Get a single record from a ServiceNow table by sys_id. If this is refused (401) while list_records works, call list_records with query="sys_id=<sys_id>" and limit=1 instead. |
| `get_system_properties` | read | query: string · limit: integer = 20 | yes | Query ServiceNow system properties |
| `get_table_schema` | read | **table_name**: string · limit: integer = 200 · include_inherited: boolean = true | yes | Get the data dictionary (field definitions) for a ServiceNow table, including inherited fields |
| `get_update_set` | read | **sys_id**: string | no | Get details of a specific update set by sys_id |
| `list_ci` | read | class_name: string = "cmdb_ci" · query: string · fields: string · limit: integer = 20 · offset: integer = 0 · response_format: "concise" \| "detailed" = "detailed" · display_value: "false" \| "true" \| "all" = "false" | yes | List CMDB configuration items with optional class and query filtering |
| `list_records` | read | **table_name**: string · query: string · fields: string · limit: integer = 20 · offset: integer = 0 · order_by: string · response_format: "concise" \| "detailed" = "detailed" · display_value: "false" \| "true" \| "all" = "false" | yes | List records from any ServiceNow table with optional filtering, field selection, and pagination |
| `list_update_set_changes` | read | **update_set_sys_id**: string · limit: integer = 50 | yes | List all customer updates (changes) within an update set |
| `list_update_sets` | read | query: string · state: string · limit: integer = 20 | yes | List update sets with optional state and query filtering |
| `set_current_update_set` | write | **sys_id**: string | no | Set an update set as the current active update set |
| `update_ci` | write, destructive | **sys_id**: string · **data**: object · class_name: string = "cmdb_ci" | no | Update a CMDB configuration item |
| `update_record` | write, destructive | **table_name**: string · **sys_id**: string · **data**: object | no | Update an existing record in a ServiceNow table |

**Resources:** `servicenow://cmdb/classes`, `servicenow://help/query-syntax`, `servicenow://instance`, `servicenow://update-set/current`; and 15 skill files for 4 skills (`analyzing-access`, `exploring-tables`, `reviewing-update-sets`, `servicenow-cmdb`).
**Resource templates:** `servicenow://schema/{table_name}`.
**Prompts:** none.
**Server instructions:** 1572 characters (the text is in contract.json).

<!-- END GENERATED -->
