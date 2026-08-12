---
description: "Review ServiceNow update sets — list sets by state, deep-review changes, compare sets, or run pre-promotion checks."
argument-hint: "[update set name, 'compare', or 'promote-check']"
allowed-tools: "mcp__plugin_servicenow_servicenow__list_update_sets, mcp__plugin_servicenow_servicenow__get_update_set, mcp__plugin_servicenow_servicenow__list_update_set_changes, mcp__plugin_servicenow_servicenow__list_records, mcp__plugin_servicenow_servicenow__aggregate_records, mcp__plugin_servicenow_servicenow__get_record, mcp__plugin_servicenow_servicenow__get_table_schema"
---

# /servicenow:review-update-set

Route based on `$ARGUMENTS`:

## No arguments
If `$ARGUMENTS` is empty:
- Run the **List & Summarize Update Sets** workflow from the `reviewing-update-sets` skill.
- Show update sets grouped by state (in progress, complete) with change counts.

## Specific update set name
If `$ARGUMENTS` is a name (not a keyword like "compare" or "promote"):
1. Find the update set: `list_update_sets(query="nameLIKE$ARGUMENTS", limit=5)`
2. If one match found, run the **Deep Review a Single Update Set** workflow — list all changes, categorize by type, flag risky changes (ACLs, script includes, schema changes).
3. If multiple matches, list them and ask the user which one to review.

## Compare request
If `$ARGUMENTS` contains "compare":
- Ask the user for two update set names (or parse them from the arguments).
- Run the **Compare Two Update Sets** workflow — find overlapping records, conflicts, dependency issues.

## Pre-promotion check
If `$ARGUMENTS` contains "promote", "promotion", "checklist", or "safe":
1. Find the update set from remaining arguments.
2. Run the **Pre-Promotion Checklist** workflow — verify state, check for Default set entries, test artifacts, risky types.
3. Generate a pass/fail promotion readiness report.

## Fallback
For any other input, search update sets by name:
- `list_update_sets(query="nameLIKE$ARGUMENTS", limit=10)`
- Present matches and offer to deep-review any of them.
