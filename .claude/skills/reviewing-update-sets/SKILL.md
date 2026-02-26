---
name: reviewing-update-sets
description: "Reviewing, analyzing, and comparing ServiceNow update sets before promotion. Shows changes, risks, dependencies, and conflicts. Use when the user mentions update sets, customizations, promotion, code review, change tracking, pre-deployment review, sys_update_xml, customer updates, \"what changed in this update set,\" or \"is this safe to promote.\""
allowed-tools: "mcp__servicenow__list_update_sets, mcp__servicenow__get_update_set, mcp__servicenow__list_update_set_changes, mcp__servicenow__list_records, mcp__servicenow__get_record, mcp__servicenow__get_table_schema"
metadata:
  author: jschuller
  version: "1.0.0"
  mcp-server: mcp-server-servicenow
---

# Reviewing ServiceNow Update Sets

Review, analyze, and compare update sets before promotion. See `references/update-set-fields.md` for update types, risk categories, and pre-promotion checklist fields.

## Workflows

### 1. List & Summarize Update Sets

Get an overview of update sets by state with change counts.

**Progress checklist** (copy into your response):
```
- [ ] List update sets by state
- [ ] Get change counts for each
- [ ] Summarize by developer and state
```

1. List update sets by state:
   ```
   list_update_sets(state="in progress", limit=20)
   list_update_sets(state="complete", limit=20)
   ```
2. For each update set, get the change count:
   ```
   list_update_set_changes(update_set_sys_id="<sys_id>", limit=1)
   ```
3. Summarize: name, state, developer, change count, last modified date.

### 2. Deep Review a Single Update Set

Examine all changes in an update set, categorize by type, and flag risks.

**Progress checklist:**
```
- [ ] Get update set details
- [ ] List all customer updates
- [ ] Categorize changes by type
- [ ] Flag risky changes (ACLs, script includes, schema changes)
- [ ] Summarize findings with risk assessment
```

1. Get the update set details:
   ```
   get_update_set(sys_id="<update_set_sys_id>")
   ```
2. List all customer updates in the set:
   ```
   list_update_set_changes(update_set_sys_id="<update_set_sys_id>", limit=100)
   ```
3. Categorize each change by type (business rule, client script, UI policy, ACL, etc.).
4. Flag risky changes — see `references/update-set-fields.md` for risk categories:
   - ACL modifications (security impact)
   - Script Includes (shared library changes)
   - Table/Column schema changes (data model impact)
   - System Properties (global configuration)
   - Scheduled Jobs (background automation)
5. Present a summary: total changes, breakdown by type, risk flags with explanations.

### 3. Compare Two Update Sets

Find overlapping records and potential conflicts between two update sets.

**Progress checklist:**
```
- [ ] Get changes for update set A
- [ ] Get changes for update set B
- [ ] Find overlapping records (same target name/table)
- [ ] Identify potential conflicts
- [ ] Report overlap and conflict details
```

1. Get all changes from both update sets:
   ```
   list_update_set_changes(update_set_sys_id="<set_a_sys_id>", limit=100)
   list_update_set_changes(update_set_sys_id="<set_b_sys_id>", limit=100)
   ```
2. Compare the change lists:
   - Overlapping records: same `target_name` modified in both sets
   - Conflicting changes: same record with different modifications
   - Dependency issues: Set A modifies a record that Set B depends on
3. Present: overlapping records, conflict details, recommended promotion order.

### 4. Pre-Promotion Checklist

Validate an update set is safe to promote using a structured checklist.

**Progress checklist:**
```
- [ ] Verify state is "complete"
- [ ] Check for Default update set entries mixed in
- [ ] Scan for test/personal artifacts
- [ ] Check for incomplete references
- [ ] Flag risky change types
- [ ] Generate promotion readiness report
```

1. Get the update set and verify state:
   ```
   get_update_set(sys_id="<update_set_sys_id>")
   ```
2. List all changes:
   ```
   list_update_set_changes(update_set_sys_id="<update_set_sys_id>", limit=100)
   ```
3. Run pre-promotion checks:
   - **State:** Must be `complete` (not `in progress`)
   - **Default set entries:** Flag any changes that belong to the Default update set
   - **Test artifacts:** Look for names containing "test", "debug", "temp", "TODO"
   - **Personal artifacts:** Check for developer-specific names or comments
   - **Risky types:** Flag ACLs, schema changes, system properties
   - **Incomplete references:** Changes that reference records not in the same set
4. Generate a promotion readiness report: pass/fail for each check, overall recommendation.

## Tips

- Update sets in `ignore` state are intentionally excluded from promotion — don't flag them.
- The `sys_update_xml` table stores the actual XML payload of each change. Query it for detailed diffs.
- Use `order_by="-sys_created_on"` to see the most recent update sets first.
- See `references/update-set-fields.md` for the full list of change types and risk categories.
