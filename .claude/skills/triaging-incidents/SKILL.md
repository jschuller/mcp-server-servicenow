---
name: triaging-incidents
description: "Creating, triaging, updating, and analyzing ServiceNow incidents. Assess severity, check affected CIs, find related incidents, and recommend assignments. Use when the user mentions incidents, INC numbers, outages, service disruptions, ticket creation, triage, priority, severity, ITSM operations, SLA breaches, assignment groups, \"what's on fire,\" or \"open P1 incidents.\""
allowed-tools: "mcp__servicenow__list_records, mcp__servicenow__get_record, mcp__servicenow__create_record, mcp__servicenow__update_record, mcp__servicenow__list_ci, mcp__servicenow__get_ci, mcp__servicenow__get_ci_relationships, mcp__servicenow__get_table_schema"
metadata:
  author: jschuller
  version: "1.0.0"
  mcp-server: mcp-server-servicenow
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
   - **Priority:** Based on impact × urgency matrix (see `references/incident-fields.md`)
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
   - `priority` is auto-calculated from impact × urgency
4. Create the incident:
   ```
   create_record(table_name="incident", data={"short_description": "...", "description": "...", "caller_id": "...", "category": "...", "impact": "3", "urgency": "3", "cmdb_ci": "..."})
   ```
5. Confirm creation: return the INC number, priority, and link.

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
2. Group by category — which categories generate the most incidents?
3. Identify repeat CIs — which CIs appear in multiple incidents?
   ```
   list_records(table_name="incident", query="cmdb_ci=<frequent_ci_sys_id>^sys_created_on>=javascript:gs.daysAgoStart(30)", fields="number,short_description,priority,state", limit=20)
   ```
4. Check for SLA breaches:
   ```
   list_records(table_name="incident", query="active=true^sla_due<javascript:gs.daysAgoEnd(0)", fields="number,short_description,priority,sla_due,assignment_group", limit=20)
   ```
5. Present: top incident categories, repeat-offender CIs, SLA breach count, recommendations for reducing incident volume.

## Tips

- The priority matrix is `impact × urgency` — see `references/incident-fields.md` for the full mapping.
- Use `active=true` to filter out resolved/closed incidents. Closed incidents have `state=7`.
- SLA fields (`sla_due`, `made_sla`) track whether response/resolution targets are met.
- Assignment groups can be looked up: `list_records(table_name="sys_user_group", query="nameLIKE<keyword>", fields="name,sys_id")`.
- See `references/incident-fields.md` for encoded query patterns and field reference.
