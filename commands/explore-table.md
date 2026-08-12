---
description: "Explore ServiceNow tables — schema discovery, field types, data profiling, table search, and comparison."
argument-hint: "[table name or search keyword]"
allowed-tools: "mcp__plugin_servicenow_servicenow__get_table_schema, mcp__plugin_servicenow_servicenow__list_records, mcp__plugin_servicenow_servicenow__aggregate_records, mcp__plugin_servicenow_servicenow__get_record, mcp__plugin_servicenow_servicenow__list_ci"
---

# /servicenow:explore-table

Route based on `$ARGUMENTS`:

## No arguments
If `$ARGUMENTS` is empty:
- Ask the user what table they'd like to explore, or suggest common starting points: `incident`, `cmdb_ci`, `change_request`, `sys_user`, `sc_req_item`.

## Known table name
If `$ARGUMENTS` looks like a ServiceNow table name (contains underscores, e.g., "incident", "cmdb_ci_server", "sys_user"):
1. Run the **Explore a Table** workflow from the `exploring-tables` skill.
2. Get schema, pull sample records, summarize field types/mandatory/reference fields.

## Compare request
If `$ARGUMENTS` contains "compare" or "vs" or "versus":
- Parse two table names from the arguments.
- Run the **Compare Tables** workflow — side-by-side schema comparison.

## Search/find request
If `$ARGUMENTS` contains "find", "search", or is a plain keyword without underscores:
- Run the **Find Tables** workflow — query `sys_db_object` for matching tables.
- `list_records(table_name="sys_db_object", query="nameLIKE$ARGUMENTS", fields="name,label,super_class,sys_id", limit=20)`
- Present matches with sample record counts.

## Profile request
If `$ARGUMENTS` contains "profile", "quality", or "audit":
- Parse the table name from remaining arguments.
- Run the **Data Profiling** workflow — sample records, check null rates, identify sparse columns.

## Fallback
For any other input, try it as a table name first:
1. `get_table_schema(table_name="$ARGUMENTS")`
2. If that fails (table doesn't exist), search for it: `list_records(table_name="sys_db_object", query="nameLIKE$ARGUMENTS^ORlabelLIKE$ARGUMENTS", fields="name,label", limit=10)`
3. Present results and offer next steps.
