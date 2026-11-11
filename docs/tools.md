# Tools, resources and skills

20 tools, 5 resources and 4 Agent Skills. The tables below are written for people; [What the model sees](#what-the-model-sees-generated) at the end is generated from the server: the tool descriptions, parameter names and types a client actually receives (the full schemas are in [contract.json](contract.json)). Every tool carries MCP annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`), so your client decides which calls need your approval. `--read-only` hides the 7 write tools, and so does an identity with `snc_read_only`.

The list tools (`list_records`, `list_ci`, `get_ci_relationships`, `get_system_properties`, `list_update_sets`, `list_update_set_changes`, `get_table_schema`, `find_references`) publish an `outputSchema` and return `structuredContent` next to the same JSON as text. A result over the 500 KB limit keeps that shape: it holds the first rows that fit and says `"truncated": true`, plus `next_offset` for the tools that take `offset`. Other tools are cut to text at the limit.

## Tools

### Table API (6)
| Tool | Description |
|------|-------------|
| `list_records` | List records from any table with filtering, field selection and pagination. Adds a `warning` when a requested field is missing from every row (it doesn't exist or an ACL hides it), and when `query=` filters on such a field or on a term that starts with an uppercase letter (a label like `Name`; columns are lowercase): the instance ignores those conditions, so the rows may be unfiltered (a dot-walk can also be missing because only the referenced records are unreadable). The fields in `query=` are checked without adding them to the returned rows; a dot-walk in `query=` is checked whole only when `fields=` is given, and at most 50 query fields are checked. Such terms are counted, never quoted, and a term the server can't parse, or a misspelled operator (`name Like x`), is not detected; field names are echoed in field-name characters only. `response_format="concise"` returns reference fields as bare sys_ids, without their instance links. `display_value="true"` returns labels in place of sys_ids and choice values, `"all"` returns `{display_value, value}` per field, and a `display_note` says that display dates are in this identity's time zone while stored values are UTC. 0 rows from `sys_journal_field` or `sys_audit` add a `warning` unless the identity visibly holds `admin` or `audit_viewer`: the instance can hide those rows instead of refusing. The value of a credential-type system property is withheld and named in the `warning`: [Credential-type system properties](#credential-type-system-properties) |
| `get_record` | Get a single record by sys_id. Takes `display_value` like `list_records`, and withholds the same values (a marker in the field; a single record has no `warning`) |
| `create_record` | Create a record in any table. The record echoed back withholds the same values, with a `warning` |
| `update_record` | Update a record. The echo is treated like `create_record`'s |
| `delete_record` | Delete a record by sys_id |
| `aggregate_records` | COUNT, AVG, MIN, MAX, SUM with GROUP BY and HAVING via the Stats API. `display_value="true"` returns group-by labels in place of sys_ids and choice values, `"all"` returns both. `having` takes `aggregate^field^operator^value`, such as `count^name^>^1`. Refuses `group_by` and aggregates on a field whose values a row read would withhold (`value` on `sys_properties`, a dot-walk to a `value` field, the old and new values of `sys_audit` and `sys_history_line`): [Credential-type system properties](#credential-type-system-properties) |

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
| `get_system_properties` | Query system properties: `name`, `value`, `description`, `type`. The value of a `password` or `password2` property is never returned: a marker takes its place and `warning` names the property ([Credential-type system properties](#credential-type-system-properties)) |
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

All off by default except the audit log and the credential-type property rule, which has no switch; flags and environment variables are in [configuration.md](configuration.md#safety-rails).

- `--read-only` hides the write tools from `tools/list` **and** refuses any non-GET request at the HTTP layer. It is the only guarantee the server itself gives about writes.
- The value of a credential-type system property (`password`, `password2`) is withheld from every tool result: [Credential-type system properties](#credential-type-system-properties), with its limits.
- When the identity holds `snc_read_only`, the write tools are hidden without any flag: ServiceNow would refuse them anyway, admin included. The server checks the caller's own `sys_user_has_role` rows once (5-second limit) for the configured account, or per token behind the OAuth proxy. This is a convenience, not a security control: if the check fails or times out, the write tools stay listed and ServiceNow refuses the write. One edge: `set_current_update_set` writes a `sys_user_preference` row, which `snc_read_only` may allow, but it is hidden with the other write tools.
- Table names, sys_ids, field lists and `order_by` are always validated; `javascript:` in caller queries is limited to `gs.*` date helpers unless `--allow-js-queries`. A field name is letters, digits and underscores, a dot-walk joined by single dots, with only spaces or tabs around it: the instance reads `value.` as `value` and returns it under that spelling, so a leading, trailing or doubled dot is refused, like any other character, a newline or a no-break space included.
- One JSON audit line per tool call or resource read. Written field values are never logged, only their names (`data_keys`); the encoded query is logged with password-, secret- and token-like values masked (and, on `sys_properties`, whatever a term compares `value` with), so it can hold other filter values such as names or emails:

```json
{"ts":"2026-08-22T19:04:11.512+00:00","run_id":"…","event":"tool_call","name":"update_record","user":"admin","auth_mode":"service-account","transport":"stdio","table":"incident","sys_id":"9d385017c611228701d22104cc95c371","data_keys":["state"],"tags":["table","write"],"outcome":"ok","duration_ms":212.4}
```

**Who approves writes:** the MCP client. Claude Code and VS Code ask before a write tool unless you allowed it; Codex auto-runs only read-only tools; Antigravity asks before every MCP tool; opencode runs MCP tools without asking unless its `permission` config says `ask`, and pi has no approval prompts, so give those two `--read-only` or a read-only identity. ServiceNow's ACLs and `snc_read_only` remain the security boundary.

### Credential-type system properties

`sys_properties.value` is a string column: whether a row's value is a credential depends on the row's `type`. ServiceNow returns the stored value of a `password` or `password2` property to any identity that can read the table (`admin` on a base instance), with every `display_value`. The server does not pass those values on, and there is no switch for it. The value is replaced with one fixed marker, `[redacted: system property value withheld as credential-type]` (in both parts of a `{display_value, value}` object), whatever `fields=` and `display_value` the call used.

| Where | What the server does |
|---|---|
| `get_system_properties`, and `list_records`, `get_record`, `list_ci`, `get_ci` on `sys_properties` | Withholds `value` when the type is `password` or `password2` (any type that starts with `password`). The list tools name the properties in `warning`; a single record carries only the marker |
| A dot-walk from another table, such as `fields="property.value"` on `sys_properties_category_m2m` | Withholds it unless the referenced record has a known plain type or a class that names another table. If the instance returns neither a `type` nor a `sys_class_name` for the record, not even empty, the value is returned: that is what a record of another table looks like (a catalog variable, say), and also a property whose two fields are both hidden from the identity |
| `create_record`, `update_record`, `create_ci`, `update_ci` | Treats the record the instance echoes back the same way, and says so in `warning`. An update of a `sys_properties` record that sets `type` to anything but a credential type is refused: from then on the stored value would be an ordinary one. The keys of `data` in a write to `sys_properties` must be plain field names. A write to `sys_metadata` that sets `type` or `value` is refused (see the limits) |
| `servicenow://instance` | Reads four fixed properties (the build and the default time zone). One that is typed as a credential is reported under `unavailable` |
| `aggregate_records` | The Stats API returns group keys, minima and maxima as bare values, without the row that says what they are. So `group_by` and the aggregate field lists are refused, on every table, when they name: `value` on `sys_properties`; the old and new values of `sys_audit` and `sys_history_line`; a dot-walk to a field called `value`, `oldvalue`, `newvalue`, `old`, `old_value`, `new` or `new_value`. Read the rows with `list_records` and `fields=` instead, and count there |
| `sys_audit` (`oldvalue`, `newvalue`) and `sys_history_line` (`old`, `old_value`, `new`, `new_value`), read from the table or through a dot-walk to it | Withholds them on rows that record a change to `sys_properties.value`. These rows don't carry the property's type, so this applies to every property, not only credential-type ones; who changed it and when stay visible. A `sys_history_line` row names its table only through `set.table`, which a read without `fields=` doesn't return: there the old and new values of any table's `value` field are withheld, so pass `fields=`. Through a dot-walk, a record that comes back with neither of the fields that say what it records is taken for a record of another table and returned: an audit row whose `tablename` and `fieldname` are both hidden from the identity looks the same |
| A field that holds a property's record XML, such as `sys_update_xml.payload` or `sys_update_version.payload` | Withholds the whole field when its text has a `<sys_properties ...>` element, whatever type the record states: the markup is not parsed, and text inside a record can imitate the part that names the type. So the payloads of ordinary properties are withheld too, and so is a script or an article that quotes such an element. The `<` is recognised plain, as an XML entity (`&lt;`, `&#60;`, `&#x3c;`, in any case and with leading zeros) and as the JSON escape `\u003c`; no other encoding is (`\x3c`, `%3C`, an entity escaped twice, base64). Which property changed, in which update set, by whom and when stays available: `list_update_set_changes`, or `list_records` on `sys_update_xml` without `payload` |

- **A name is judged by every segment.** `value.zz` is treated as `value`, and `property.value.zz` as the dot-walk `property.value`, in `fields=` and in the aggregate arguments, whatever the instance would make of the rest.
- **The stored type decides.** When `fields=` leaves out the fields that say what a row is (`type`; `<reference>.type` and `<reference>.sys_class_name` for a dot-walk; `tablename` and `fieldname` on `sys_audit`; `set.table` and `field` on `sys_history_line`), or names them in another spelling, the server asks the instance for them as well and removes them from the rows again. A display label is not the stored type (`boolean` is labelled `true | false`), so on these tables `display_value="true"` is read from the instance as `"all"` and reduced to the display form before it is returned.
- **An unreadable type fails closed.** The value is returned only for the known plain types (`boolean`, `choicelist`, `color`, `date_format`, `image`, `integer`, `short_string`, `string`, `time_format`, `timezone`, `uploaded_image`). If `type` is missing from a row (an ACL can hide it), empty, or anything else, the value is withheld and the `warning` says so; a base instance has a handful of such properties. The same holds for an audit row that doesn't say which table and field it records.
- **Set or empty stays visible.** An empty value is returned empty, so a health check can still tell whether a credential is configured. The marker has one length, whatever it replaces.
- **No result is logged.** The audit line has no field for a result. It holds the caller's query: there, on `sys_properties`, whatever a term compares `value` with is masked; other filter text is kept. A query is logged by its length only (`<query of N characters, not logged>`) when the masks can't be trusted on it: over 4,000 characters, a run of nine or more spaces or tabs, a name of more than 80 characters, or, on `sys_properties`, a text-search term (`123TEXTQUERY321`, `IR_...`), a related-list or sub-query or a join, each of which can compare `value` without naming it. The `error` field holds the first 200 characters of an error's text, which is this server's wording, the argument it refused, or ServiceNow's own error message and detail when the instance sent one. An answer the server did not expect (a body that is no JSON, a result that is no record) is described by what kind of thing it is, never quoted.

**Limits.** "Not returned" is not "impossible to infer", and the rule covers system properties only:

- A query that filters on `value` (or searches text) still shows which properties match, and `aggregate_records` still counts them. An identity that can read `sys_properties` can therefore work a value out with enough such queries, each of them in the audit log: this rule keeps values out of results, it does not make them secret from that identity. When a value filter matches a withheld row, the `warning` says that the match itself tells something about the value. The server does not refuse these filters: finding the properties that mention a host name is ordinary admin work, ordering by `value` and filters on a dot-walked or audited copy give the same kind of hint, and a refusal that covers only some of them would promise more than it keeps.
- The rule covers what the server reads, not what an identity can do. One that can write to the instance as `admin` has routes to a value that no read rule sees, and they need no script. An example: a write to the dictionary entry of `sys_properties.value` that makes it the table's display field turns every value into the display value of each reference to its property, and a display value is returned like any label. `--read-only`, or a read-only identity, closes these routes; the write tools are not meant for an identity that must not learn these values.
- Only the type decides. A secret kept in a `string` property is returned like any other string.
- Credential fields of other tables (`oauth_entity`, `sys_auth_profile_basic`, `discovery_credentials` and the like) come back as the instance returns them. Keep the integration identity away from those tables with ACLs and REST API access policies.
- A table that extends `sys_properties`, or a database view over it, is not recognised as holding properties. The table it extends, `sys_metadata`, was checked on a Brazil instance (2026-11-11): a read of `value` through it returns no such field. Writes through it were not tested: one that sets `type` or `value` is refused.
- A dot-walk is judged by the referenced record's `type` and `sys_class_name`. If the instance returns the walked `value` and neither of those fields, not even empty, the server takes the record for one of another table and returns it. A record of another table that has a `type` the server doesn't know and no class is withheld, though it is no property.
- Copies of a value that the instance keeps in free text (a log line, an email, an attachment) are not recognised, nor is record XML that is encoded more than once.

## What the model sees (generated)

<!-- BEGIN GENERATED by scripts/contract.py: do not edit by hand -->

Read from the server itself with the default settings (skills on, write tools served) by `scripts/contract.py`. The descriptions, parameter names and types are the ones the model reads; the tables above are written for people. The full contract, with input and output schemas, annotations, resources, the server instructions and what the server negotiates, is [contract.json](contract.json). Tests fail when either drifts from the code: `uv run --frozen --extra dev python scripts/contract.py --write` regenerates both.

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
| `get_system_properties` | read | query: string · limit: integer = 20 | yes | Query ServiceNow system properties: name, value, description and type. The value of a credential-type property (type password or password2) is never returned: a marker takes its place, and warning names the property. |
| `get_table_schema` | read | **table_name**: string · limit: integer = 200 · include_inherited: boolean = true | yes | Get the data dictionary (field definitions) for a ServiceNow table, including inherited fields |
| `get_update_set` | read | **sys_id**: string | no | Get details of a specific update set by sys_id |
| `list_ci` | read | class_name: string = "cmdb_ci" · query: string · fields: string · limit: integer = 20 · offset: integer = 0 · response_format: "concise" \| "detailed" = "detailed" · display_value: "false" \| "true" \| "all" = "false" | yes | List CMDB configuration items with optional class and query filtering |
| `list_records` | read | **table_name**: string · query: string · fields: string · limit: integer = 20 · offset: integer = 0 · order_by: string · response_format: "concise" \| "detailed" = "detailed" · display_value: "false" \| "true" \| "all" = "false" | yes | List records from any ServiceNow table with optional filtering, field selection, and pagination |
| `list_update_set_changes` | read | **update_set_sys_id**: string · limit: integer = 50 | yes | List all customer updates (changes) within an update set |
| `list_update_sets` | read | query: string · state: string · limit: integer = 20 | yes | List update sets with optional state and query filtering |
| `set_current_update_set` | write | **sys_id**: string | no | Set an update set as the current active update set |
| `update_ci` | write, destructive | **sys_id**: string · **data**: object · class_name: string = "cmdb_ci" | no | Update a CMDB configuration item |
| `update_record` | write, destructive | **table_name**: string · **sys_id**: string · **data**: object | no | Update an existing record in a ServiceNow table |

- **Resources:** `servicenow://cmdb/classes`, `servicenow://help/query-syntax`, `servicenow://instance`, `servicenow://update-set/current`; and 15 skill files for 4 skills (`analyzing-access`, `exploring-tables`, `reviewing-update-sets`, `servicenow-cmdb`).
- **Resource templates:** `servicenow://schema/{table_name}`.
- **Prompts:** none.
- **Server instructions:** 1572 characters (the text is in contract.json).
- **`server/discover`** (what a current client negotiates): `2026-07-28` (supported: `2026-07-28`), capabilities `logging`, `prompts`, `resources`, `tools`, extensions `io.modelcontextprotocol/ui`.
- **`initialize`** (the handshake, offered the newest version it covers): `2025-11-25`, capabilities `logging`, `prompts`, `resources`, `tools`. The capability flags are in contract.json.

<!-- END GENERATED -->
