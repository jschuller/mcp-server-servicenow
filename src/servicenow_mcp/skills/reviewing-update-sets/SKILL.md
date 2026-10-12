---
name: reviewing-update-sets
description: "Reviewing, analyzing, and comparing ServiceNow update sets before promotion, singly or in batches. Shows changes, risks, dependencies, and conflicts. Use when the user mentions update sets, customizations, promotion, code review, change tracking, pre-deployment review, sys_update_xml, customer updates, 'what changed in this update set', or 'is this safe to promote'."
license: MIT
metadata:
  author: jschuller
  version: "2.0.0"
  io.github.jschuller/servicenow-roles: "admin"
  io.github.jschuller/servicenow-tables: "sys_update_set sys_update_xml sys_remote_update_set sys_update_preview_problem sys_update_version"

---

# Reviewing ServiceNow Update Sets

Review, analyze, and compare update sets before promotion, and read the preview problems of retrieved (remote) update sets. See `references/update-set-fields.md` for update types, risk categories, preview problem types and pre-promotion checklist fields.

## Tables and roles

This skill needs an **admin-level identity**. Every table it reads returns 403 or no rows for `itil` + `snc_read_only`.

| Table | What it holds |
|-------|---------------|
| `sys_update_set` | Local update sets |
| `sys_update_xml` | One row per captured change |
| `sys_remote_update_set` | Update sets retrieved from another instance, with a `state` and a `collisions` count |
| `sys_update_preview_problem` | Problems a preview found for a retrieved set |
| `sys_update_version` | Version history of each customised record |

## When access is denied

- **403** on `sys_update_set` (or `list_update_sets` fails): the review is not assessable with this identity. Say an admin-level identity is needed, and stop rather than guess.
- **0 rows** from `sys_update_preview_problem`: either nothing was found or the rows are hidden. Check the set's `collisions` count and state before calling a set clean.

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
4. **Batch review** (all sets in one state, e.g. everything "complete" awaiting promotion): for each set run the Deep Review steps below in brief — categorize changes by type, flag high-risk items — then check for cross-set conflicts (the same `target_name` / `name` in `sys_update_xml` across two sets), give each set a promotion-readiness verdict, and recommend a promotion order that respects dependencies.

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

### 5. Preview Problems and Collisions (retrieved update sets)

Read what a preview already found, without running one. Previewing, accepting, skipping and committing all write to the instance, so leave them to the user.

**Progress checklist:**
```
- [ ] List retrieved update sets and their states
- [ ] Read the preview problems of the set under review
- [ ] Group problems by type and resolution status
- [ ] For collisions, compare record versions
- [ ] Recommend accept, skip or fix for each open problem
```

1. List retrieved sets, newest first:
   ```
   list_records(table_name="sys_remote_update_set", query="stateINloaded,previewed", fields="name,state,collisions,commit_date,application,update_source", limit=20, order_by="-sys_created_on")
   ```
   `loaded` means the set was retrieved but not previewed. `previewed` means a preview ran and its problems are recorded.
2. Read the problems for one set:
   ```
   list_records(table_name="sys_update_preview_problem", query="remote_update_set=<remote_update_set_sys_id>", fields="type,status,description,missing_item,missing_item_table,remote_update", limit=200)
   ```
   - `type` is `error` or `warning`.
   - `status` stays empty until someone resolves the problem, then it reads `ignored`, `skipped` or `skip_collision`.
   - Unresolved errors block the commit.
3. Classify each open problem with `references/update-set-fields.md` (missing object, collision, uncommitted update ...).
4. For a collision, compare the versions of the record on this instance:
   ```
   list_records(table_name="sys_update_version", query="name=<update_name>", fields="name,state,source_table,source,sys_recorded_at", limit=10, order_by="-sys_recorded_at")
   ```
   Never request `payload`: it holds the full record XML and can contain credentials.
5. Report: open errors first, then warnings. For each one, give a recommendation (accept the remote update, skip it, or fix the missing dependency first) and say who should act.

## Tips

- Update sets in `ignore` state are intentionally excluded from promotion — don't flag them.
- The `sys_update_xml` table stores the actual XML payload of each change. Query it for detailed diffs only when needed, with small limits: payloads can contain credentials and script bodies.
- Use `order_by="-sys_created_on"` to see the most recent update sets first.
- See `references/update-set-fields.md` for the full list of change types and risk categories.
