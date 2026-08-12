---
description: "Explore CMDB — CI hierarchy, dependencies, health metrics, data quality, and CSDM service taxonomy."
argument-hint: "[CI name, 'health', 'csdm', or class name]"
allowed-tools: "mcp__plugin_servicenow_servicenow__list_ci, mcp__plugin_servicenow_servicenow__get_ci, mcp__plugin_servicenow_servicenow__get_ci_relationships, mcp__plugin_servicenow_servicenow__list_records, mcp__plugin_servicenow_servicenow__aggregate_records, mcp__plugin_servicenow_servicenow__get_record, mcp__plugin_servicenow_servicenow__get_table_schema"
---

# /servicenow:cmdb

Route based on `$ARGUMENTS`:

## No arguments
If `$ARGUMENTS` is empty:
- Run the **Explore CI Class Hierarchy** workflow from the `servicenow-cmdb` skill.
- Show which CI classes are populated and their record counts.

## Health request
If `$ARGUMENTS` contains "health", "quality", "score", or "audit":
- Run the **Assess CMDB Health** workflow — query health audit results, active rules, scores by class.
- If "quality" or "data quality" is mentioned, also run the **Investigate Data Quality** workflow.

## CSDM request
If `$ARGUMENTS` contains "csdm", "service", "taxonomy", or "business service":
- Run the **CSDM Service Taxonomy** workflow — list business/technical/application services, map relationships.

## Specific CI name
If `$ARGUMENTS` looks like a CI name (not a keyword):
1. Find the CI: `list_ci(query="nameLIKE$ARGUMENTS", limit=10)`
2. If found, run the **Map CI Dependencies** workflow — get CI details, trace relationships upstream and downstream.
3. If not found, suggest broadening the search or checking the class name.

## CI class name
If `$ARGUMENTS` looks like a CMDB class (starts with "cmdb_ci_"):
1. Get the class schema: `get_table_schema(table_name="$ARGUMENTS")`
2. List CIs in that class: `list_ci(class_name="$ARGUMENTS", limit=20)`
3. Summarize: field count, populated records, key fields.

## Dependencies request
If `$ARGUMENTS` contains "depends", "dependencies", "upstream", or "downstream":
- Parse the CI name from remaining arguments.
- Run the **Map CI Dependencies** workflow.

## Fallback
For any other input, search for CIs matching the term:
- `list_ci(query="nameLIKE$ARGUMENTS", limit=10)`
- Present matches and offer to map dependencies or explore the CI class.
