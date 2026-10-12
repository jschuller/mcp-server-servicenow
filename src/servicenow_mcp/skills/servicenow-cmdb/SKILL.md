---
name: servicenow-cmdb
description: "Auditing the CMDB as a data model: CI class hierarchy, raw relationships, CMDB health scorecards, data quality (duplicates, orphans, staleness, missing fields) and CSDM 5 conformance. Use when the user mentions CMDB health, CMDB audit, data quality, duplicates, orphaned or stale CIs, CI classes, relationships in cmdb_rel_ci, CSDM, service taxonomy, Data Foundations, compliance scores, or 'how clean is our CMDB'."
license: MIT
metadata:
  author: jschuller
  version: "2.0.0"
  io.github.jschuller/servicenow-roles: "cmdb_read sn_cmdb_user snc_read_only"
  io.github.jschuller/servicenow-tables: "cmdb_ci cmdb_rel_ci sys_db_object service_offering dl_definition cmdb_health_scorecard cmdb_health_result cmdb_health_metric cmdb_health_staleness_rule cmdb_health_orphan_rule sn_getwell_csdm_score"

---

# ServiceNow CMDB Data Foundations

Audit the CMDB as a data model: explore CI classes, read raw relationships, assess CMDB health, investigate data quality, review the CSDM service taxonomy, and score CSDM conformance by stage. This is platform data work, read-only.

For conversational CI search, service topology and change impact, ServiceNow ships its own CMDB MCP server (with Otto for CMDB). It has no health, staleness, duplicate or CSDM conformance tools; that is what this skill covers. See `references/cmdb-tables.md` for CI classes, health KPIs, CSDM mappings and encoded query syntax, and `references/csdm5.md` for CSDM 5 stages and the conformance scores.

## Tables and roles

| Tables | Readable with |
|--------|---------------|
| `cmdb_ci` and most CI classes, `cmdb_rel_ci`, `service_offering`, `sn_getwell_csdm_score` | `cmdb_read` ("CMDB reader"); `itil` contains it. `snc_read_only` alone gets 403 on `cmdb_ci` and the scores |
| `cmdb_health_scorecard`, `cmdb_health_result`, `cmdb_health_metric`, the health rules | `sn_cmdb_user` (CMDB Workspace, read-only) or `itil`; `cmdb_read` alone is not enough |
| Service classes such as `cmdb_ci_service_business` and `cmdb_ci_service_technical` | Often a service or CMDB role beyond `itil`: expect 403 |
| `sys_db_object` (class hierarchy) | `itil` and many other roles; `servicenow://cmdb/classes` reads it for you |

Add `snc_read_only` to keep the identity read-only. These are the read ACLs on a Brazil instance; yours may differ. Creating or updating CIs needs `sn_cmdb_editor`: since Zurich, `itil` no longer contains it.

## When access is denied

- A **403** on a class or table means not assessable with this identity. Name it in the report as a gap, and keep going with the classes you can read.
- **0 rows** from a class can mean the class is empty or that ACLs hide its rows. Don't report "no services" when the read might be filtered.
- Health and score tables stay empty until their scheduled jobs have run. Empty is not the same as healthy.

## Workflows

### 1. Explore CI Class Hierarchy

Discover what CI classes exist and their structure.

**Progress checklist** (copy into your response):
```
- [ ] Get base CI table schema
- [ ] Sample populated CI classes
- [ ] Check class-specific fields
- [ ] Summarize class inventory
```

1. Get the base CI table schema:
   ```
   get_table_schema(table_name="cmdb_ci")
   ```
2. List CIs by class to see what's populated:
   ```
   list_ci(class_name="cmdb_ci_server", limit=10)
   list_ci(class_name="cmdb_ci_computer", limit=10)
   list_ci(class_name="cmdb_ci_app_server", limit=10)
   ```
3. Check class-specific fields by getting the schema for a subclass:
   ```
   get_table_schema(table_name="cmdb_ci_server")
   ```
4. Summarize which classes have data and how many CIs each contains.

### 2. Map CI Dependencies

Trace upstream and downstream dependencies for a given CI.

**Progress checklist:**
```
- [ ] Find target CI
- [ ] Get CI details
- [ ] Get relationships
- [ ] Build dependency tree
- [ ] Present upstream/downstream map
```

1. Find the target CI:
   ```
   list_ci(class_name="cmdb_ci", query="nameLIKE<search_term>", limit=10)
   ```
2. Get the CI details:
   ```
   get_ci(sys_id="<ci_sys_id>")
   ```
3. Get all relationships:
   ```
   get_ci_relationships(sys_id="<ci_sys_id>")
   ```
4. For each related CI, optionally recurse one level deeper to build a dependency map.
5. Present results as an upstream/downstream tree showing relationship types.

### 3. Assess CMDB Health

Query the CMDB Health Dashboard tables for data quality KPIs. Uses a validation loop: assess -> identify issues -> remediate -> re-assess.

**Progress checklist:**
```
- [ ] Read the latest health scores
- [ ] Read the last processing cycle's results
- [ ] Check which KPIs and metrics are enabled
- [ ] Check the staleness and orphan rules behind them
- [ ] Recommend remediation actions
- [ ] (Optional) Re-assess after fixes
```

1. Latest scores (the newest rows are current; older rows are kept as history):
   ```
   list_records(table_name="cmdb_health_scorecard", limit=20, order_by="-sys_created_on")
   ```
2. Results from the most recent processing cycle:
   ```
   list_records(table_name="cmdb_health_result", limit=20, order_by="-sys_created_on")
   ```
3. Which KPIs and metrics are tracked, and how they are configured:
   ```
   list_records(table_name="cmdb_health_metric", fields="name,friendly_name,description,parent", limit=50)
   ```
4. The rules that decide what counts as stale or orphaned, per class:
   ```
   list_records(table_name="cmdb_health_staleness_rule", fields="applies_to,duration", limit=50)
   list_records(table_name="cmdb_health_orphan_rule", limit=50)
   ```
   `cmdb_health_metric_status` shows whether each KPI's last run completed, hit its failure limit or timed out; `cmdb_health_config` holds the inclusion rules (which classes are scored).
5. Summarize: overall and per-KPI scores, the weakest classes, and missing rules (a class with no staleness or orphan rule is not scored for it).
6. Recommend specific remediation actions for each weak KPI.
7. After remediation, re-query the scores to verify improvement. Scores change only when the CMDB Health jobs run again, so say when that is.

Empty scorecard and result tables mean the CMDB Health jobs have not run (common on a developer instance): say so and use the full audit below instead.
8. **Full CMDB audit** (when asked for an audit or the health tables are empty): enumerate the populated CI classes (`list_records(table_name="sys_db_object", query="super_classISNOTEMPTY^nameSTARTSWITHcmdb_ci", fields="name,label", limit=100)` then `aggregate_records` per class), sample records per class for missing key fields (`name`, `sys_class_name`, `operational_status`, `support_group`), find orphaned CIs (no `cmdb_rel_ci` rows in either direction), flag duplicates (same `name` across classes), and close with a findings-then-recommendations report. Keep it read-only unless the user asks for fixes.

### 4. Investigate Data Quality

Drill into data quality issues for specific CI classes. Uses a validation loop: profile -> identify gaps -> suggest fixes.

**Progress checklist:**
```
- [ ] Find CIs with missing mandatory fields
- [ ] Check for duplicates
- [ ] Check for orphaned CIs (no relationships)
- [ ] Query data quality rules
- [ ] Report issues by category with recommendations
```

1. Find CIs with missing mandatory fields:
   ```
   list_ci(class_name="cmdb_ci_server", query="ip_addressISEMPTY", limit=20)
   ```
2. Find duplicate CIs (same name, different sys_id):
   ```
   list_ci(class_name="cmdb_ci_server", query="nameLIKE<name>", limit=20)
   ```
3. Check for orphaned CIs (no relationships):
   ```
   get_ci_relationships(sys_id="<ci_sys_id>")
   ```
4. Query data quality rules:
   ```
   list_records(table_name="dl_definition", query="active=true", limit=20)
   ```
5. Report: count of issues by category, affected CI classes, recommended actions.

### 5. CSDM Service Taxonomy

Explore the Common Service Data Model service hierarchy.

**Progress checklist:**
```
- [ ] List Business Services
- [ ] List Technical Services
- [ ] List Application Services
- [ ] Map service relationships
- [ ] Check service-to-offering mappings
- [ ] Present service taxonomy tree
```

1. List Business Services:
   ```
   list_ci(class_name="cmdb_ci_service_business", limit=20)
   ```
2. List Technical Services:
   ```
   list_ci(class_name="cmdb_ci_service_technical", limit=20)
   ```
3. List Application Services. CSDM 5 calls them Service Instances (`cmdb_ci_service_auto` and its subclasses):
   ```
   list_ci(class_name="cmdb_ci_service", query="sys_class_nameLIKEservice", limit=20)
   ```
4. For a specific service, map relationships to see which CIs support it:
   ```
   get_ci_relationships(sys_id="<service_sys_id>")
   ```
5. Check service-to-offering mappings:
   ```
   list_records(table_name="service_offering", limit=20)
   ```
6. Present the service taxonomy: business -> technical -> application services, with supporting CIs.

### 6. CSDM 5 Conformance by Stage

Score how far the instance has adopted CSDM, using the scores ServiceNow's CSDM Data Foundations dashboard computes. Read `references/csdm5.md` first.

**Progress checklist:**
```
- [ ] Read the active CSDM scores
- [ ] Group them by stage: Foundation, Crawl, Walk, Run, Fly
- [ ] List the failing metrics per stage, highest priority first
- [ ] Recommend the next stage's work
```

1. Read every active score:
   ```
   list_records(table_name="sn_getwell_csdm_score", query="active=true", fields="name,csdm_stage,result,count,priority", limit=100, order_by="csdm_stage")
   ```
2. `csdm_stage` is stored as a number: 5 Foundation, 1 Crawl, 2 Walk, 3 Run, 4 Fly. `result` is a percentage, where 100 means the data is complete for that metric, and `count` is the number of records the metric looked at.
3. Metrics that are not yet complete:
   ```
   list_records(table_name="sn_getwell_csdm_score", query="active=true^result<100", fields="name,csdm_stage,result,count,priority", limit=100, order_by="priority")
   ```
4. Report stage by stage, starting with Foundation: how many metrics are complete, which are not, and with what counts. A stage is only worth building on when the one before it is in good shape.
5. If the table is empty, the daily "CSDM Get Well Metric Collection" job has not run yet. If it returns 403, say the scores are not readable with this identity.

## Tips

- Use `fields` parameter on `list_ci` and `list_records` to limit returned data to relevant columns.
- CMDB health tables may not exist on all instances — if a table returns 404, the Health Dashboard module may not be activated.
- Metric names on the instance can lag the CSDM version: a CSDM 5 instance may still show "Consumes::Consumed By" where CSDM 5 says "Uses::Used By".
- CSDM class names vary by SN version. If a class returns no results, try `get_table_schema` to confirm it exists.
- See `references/cmdb-tables.md` for encoded query syntax, CI class reference, and health KPI definitions.
