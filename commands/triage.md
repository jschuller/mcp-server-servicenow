---
description: "Triage ServiceNow incidents — list open incidents, assess priority, investigate a specific INC, or analyze trends."
argument-hint: "[INC number, priority filter, or description]"
allowed-tools: "mcp__plugin_servicenow_servicenow__list_records, mcp__plugin_servicenow_servicenow__aggregate_records, mcp__plugin_servicenow_servicenow__get_record, mcp__plugin_servicenow_servicenow__create_record, mcp__plugin_servicenow_servicenow__update_record, mcp__plugin_servicenow_servicenow__list_ci, mcp__plugin_servicenow_servicenow__get_ci, mcp__plugin_servicenow_servicenow__get_ci_relationships, mcp__plugin_servicenow_servicenow__get_table_schema"
---

# /servicenow:triage

Route based on `$ARGUMENTS`:

## No arguments or general request
If `$ARGUMENTS` is empty, contains "what's on fire", "open", "recent", or "list":
- Run the **List Recent Incidents** workflow from the `triaging-incidents` skill.
- Show open incidents sorted by priority, highlight any P1/P2.

## Specific INC number
If `$ARGUMENTS` contains an INC number (e.g., "INC0010001"):
1. Find the incident: `list_records(table_name="incident", query="number=$ARGUMENTS", limit=1)`
2. Run the **Investigate an Incident** workflow — get full details, check CI dependencies, find similar incidents, check related problems/changes.
3. Present findings with recommended actions.

## Priority filter
If `$ARGUMENTS` contains "P1", "P2", "critical", or "high priority":
- Filter incidents by the specified priority level.
- Run the **List Recent Incidents** workflow with the appropriate priority filter.

## Triage request
If `$ARGUMENTS` contains "triage", "assess", or "new":
- Run the **Triage a New Incident** workflow — assess impact/urgency, check CI blast radius, suggest priority and assignment.

## Trend analysis
If `$ARGUMENTS` contains "trends", "analysis", "bulk", or "SLA":
- Run the **Bulk Analysis** workflow — top categories, repeat CIs, SLA breaches.

## Fallback
For any other input, treat `$ARGUMENTS` as a search term:
- `list_records(table_name="incident", query="short_descriptionLIKE$ARGUMENTS^active=true", limit=10)`
- Present matching incidents and offer to investigate any of them.
