---
name: triaging-incidents
description: "Creating, triaging, updating, and analyzing ServiceNow incidents, including trend reports. Assess severity, check affected CIs, find related incidents, and recommend assignments. Use when the user mentions incidents, INC numbers, outages, service disruptions, ticket creation, triage, priority, severity, ITSM operations, SLA breaches, assignment groups, incident trends, 'what's on fire', or 'open P1 incidents'."
license: MIT
metadata:
  author: jschuller
  version: "2.0.0"

---

# Triaging ServiceNow Incidents

Create, triage, investigate, and analyze incidents. See `references/incident-fields.md` for the priority matrix, states, categories, and encoded query patterns.

## Workflows

### 1. List Recent Incidents

Get a summary of recent incidents by priority, state, or assignment group.

**Progress checklist** (copy into your response):
```
- [ ] Query incidents with filters
- [ ] Summarize by priority and state
- [ ] Highlight critical/P1 incidents
```

1. List recent incidents (last 24 hours, open):
   ```
   list_records(table_name="incident", query="active=true^sys_created_on>=javascript:gs.daysAgoStart(1)", fields="number,short_description,priority,state,assignment_group,assigned_to,sys_created_on", limit=20, order_by="-priority")
   ```
2. For a specific assignment group:
   ```
   list_records(table_name="incident", query="active=true^assignment_groupLIKE<group_name>", fields="number,short_description,priority,state,assigned_to", limit=20)
   ```
3. Summarize: total count, breakdown by priority (P1/P2/P3/P4), breakdown by state, highlight any P1/P2 incidents.

### 2. Triage a New Incident

Assess impact and urgency, then suggest priority, category, and assignment group.

**Progress checklist:**
```
- [ ] Get incident details
- [ ] Assess impact and urgency
- [ ] Check affected CI and its dependencies
- [ ] Suggest priority, category, assignment group
- [ ] Recommend next steps
```

1. Get the incident details:
   ```
   get_record(table_name="incident", sys_id="<incident_sys_id>")
   ```
2. If a CI is attached, check its relationships to assess blast radius:
   ```
   get_ci(sys_id="<cmdb_ci_sys_id>")
   get_ci_relationships(sys_id="<cmdb_ci_sys_id>")
   ```
3. Look for similar recent incidents (same CI or category):
   ```
   list_records(table_name="incident", query="cmdb_ci=<ci_sys_id>^sys_created_on>=javascript:gs.daysAgoStart(30)", fields="number,short_description,state,priority", limit=10)
   ```
4. Recommend triage decisions:
   - **Priority:** Based on impact x urgency matrix (see `references/incident-fields.md`)
   - **Category:** Based on the affected CI class and description keywords
   - **Assignment group:** Based on CI ownership or category routing rules
5. Present recommendations with reasoning.

### 3. Investigate an Incident

Deep-dive into an existing incident — full context, related CIs, similar incidents.

**Progress checklist:**
```
- [ ] Get full incident details
- [ ] Get affected CI details and relationships
- [ ] Find similar recent incidents
- [ ] Check for related problems or changes
- [ ] Summarize findings and recommend actions
```

1. Get the full incident record:
   ```
   get_record(table_name="incident", sys_id="<incident_sys_id>")
   ```
2. If a CI is attached, get its details and dependency chain:
   ```
   get_ci(sys_id="<cmdb_ci_sys_id>")
   get_ci_relationships(sys_id="<cmdb_ci_sys_id>")
   ```
3. Find similar recent incidents:
   ```
   list_records(table_name="incident", query="categoryLIKE<category>^sys_created_on>=javascript:gs.daysAgoStart(30)", fields="number,short_description,state,priority,resolution_notes", limit=10)
   ```
4. Check for related problems:
   ```
   list_records(table_name="problem", query="cmdb_ci=<ci_sys_id>^active=true", fields="number,short_description,state", limit=5)
   ```
5. Check for recent changes on the same CI:
   ```
   list_records(table_name="change_request", query="cmdb_ci=<ci_sys_id>^sys_created_on>=javascript:gs.daysAgoStart(7)", fields="number,short_description,state,type", limit=5)
   ```
6. Summarize: incident context, CI dependency impact, related incidents/problems/changes, recommended actions.

### 4. Create an Incident

Create a new incident with validated fields and appropriate defaults.

**Progress checklist:**
```
- [ ] Validate required fields are provided
- [ ] Suggest category from description
- [ ] Set appropriate defaults (state, priority)
- [ ] Create the incident
- [ ] Confirm creation with INC number
```

1. Validate required fields: `short_description` is mandatory. Confirm `caller_id` is provided.
2. Suggest category based on description keywords (see `references/incident-fields.md`).
3. Set defaults for missing fields:
   - `state`: 1 (New)
   - `impact`: 3 (Low) unless specified
   - `urgency`: 3 (Low) unless specified
   - `priority` is auto-calculated from impact x urgency
4. Create the incident:
   ```
   create_record(table_name="incident", data={"short_description": "...", "description": "...", "caller_id": "...", "category": "...", "impact": "3", "urgency": "3", "cmdb_ci": "..."})
   ```
5. Confirm creation: return the INC number, priority, and link.

If `create_record` is not among your tools, the identity is read-only: give the user the field values to enter instead.

### 5. Bulk Analysis

Analyze incident trends — top categories, repeat offenders, SLA status.

**Progress checklist:**
```
- [ ] Pull recent incidents (7-30 day window)
- [ ] Group by category
- [ ] Identify repeat CIs (frequent flyers)
- [ ] Check SLA breaches
- [ ] Present trends and recommendations
```

1. Pull recent incidents:
   ```
   list_records(table_name="incident", query="sys_created_on>=javascript:gs.daysAgoStart(30)^active=true", fields="number,category,cmdb_ci,priority,state,assignment_group,sla_due", limit=100, order_by="-sys_created_on")
   ```
2. Group by category, priority, and assignment group — which generate the most incidents? `aggregate_records(table_name="incident", query="sys_created_on>=javascript:gs.daysAgoStart(30)", group_by="category")` avoids pulling every row.
3. Identify repeat CIs — which CIs appear in multiple incidents?
   ```
   list_records(table_name="incident", query="cmdb_ci=<frequent_ci_sys_id>^sys_created_on>=javascript:gs.daysAgoStart(30)", fields="number,short_description,priority,state", limit=20)
   ```
4. Check for SLA breaches:
   ```
   list_records(table_name="incident", query="active=true^sla_due<javascript:gs.daysAgoEnd(0)", fields="number,short_description,priority,sla_due,assignment_group", limit=20)
   ```
5. Find resolution patterns: which categories resolve fastest and slowest (`resolved_at` minus `opened_at` on closed incidents, `state=7`, same window).
6. Present as a trend report: top incident categories, repeat-offender CIs, SLA breach count, resolution patterns, and recommendations for reducing incident volume. Separate facts from recommendations.

## Tips

- The priority matrix is `impact x urgency` — see `references/incident-fields.md` for the full mapping.
- Use `active=true` to filter out resolved/closed incidents. Closed incidents have `state=7`.
- SLA fields (`sla_due`, `made_sla`) track whether response/resolution targets are met.
- Assignment groups can be looked up: `list_records(table_name="sys_user_group", query="nameLIKE<keyword>", fields="name,sys_id")`.
- See `references/incident-fields.md` for encoded query patterns and field reference.

## Notes on writes

`update_record` changes the incident immediately. Before a change the user did not ask for in so many words, show the record's current values and the change, and wait for their go. In a subagent or headless run, report the proposed change instead of making it. If write tools are unavailable (a read-only identity or `--read-only`), propose the change instead.
