---
name: servicenow-cmdb
description: "Auditing the CMDB as a data model: CI class hierarchy, raw relationships, CMDB health scorecards, data quality (duplicates, orphans, staleness, missing fields) and CSDM 5 conformance. Use when the user mentions CMDB health, CMDB audit, data quality, duplicates, orphaned or stale CIs, CI classes, relationships in cmdb_rel_ci, CSDM, service taxonomy, Data Foundations, compliance scores, or 'how clean is our CMDB'."
license: MIT
metadata:
  author: jschuller
  version: "2.1.0"
  io.github.jschuller/servicenow-roles: "cmdb_read sn_cmdb_user itil snc_read_only"
  io.github.jschuller/servicenow-tables: "cmdb_ci cmdb_rel_ci sys_db_object service_offering cmdb_health_scorecard cmdb_health_result cmdb_health_metric cmdb_health_staleness_rule cmdb_health_orphan_rule sn_getwell_csdm_score reconcile_duplicate_task cmn_location cmdb_model alm_hardware"

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
| `cmn_location`, `cmdb_model`, `alm_hardware` | `itil` |
| `reconcile_duplicate_task` (de-duplication tasks) | Returned 0 rows to `itil` + `snc_read_only` on a developer instance: empty or hidden, the call can't tell which |

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
8. **Full CMDB audit** (when asked for an audit or the health tables are empty): count the populated CI classes (`aggregate_records(table_name="cmdb_ci", group_by="sys_class_name")`; `list_records(table_name="sys_db_object", query="super_classISNOTEMPTY^nameSTARTSWITHcmdb_ci", fields="name,label", limit=100)` gives their labels), then run every check in workflow 4 on the classes that matter most (hardware, servers, VM instances, applications). Close with a findings-then-recommendations report that gives each finding as a count over its total and a percentage. Keep it read-only unless the user asks for fixes.

### 4. Investigate Data Quality

Measure each problem as a count over a total, so that the report can give a percentage, then read a few rows to show what the problem looks like. `references/cmdb-tables.md` (Data Quality Checks) says what each field means and how ServiceNow's dashboards define the same checks.

**Progress checklist:**
```
- [ ] Count the classes to check (the denominators)
- [ ] Duplicates: tagged by IRE, and the same name within a class
- [ ] Stale CIs: not updated, not discovered
- [ ] Orphans and broken relationships
- [ ] Missing key fields per class
- [ ] Locations, models and assets
- [ ] Report each check as count / total and percent, with a sample
```

Each check is one `aggregate_records` call for the problem rows and the same call without the check's own condition for the total. Then read up to 5 rows with `fields=` as examples. `list_ci` and `list_records` also check the fields in `query=`: a hidden or misspelled one shows up in the sample's warning. `display_value="all"` adds labels (class, status, location names) to a sample; every query here works without it.

If `aggregate_records` is refused (a 401 under API-key auth means no REST API access policy covers the Aggregate API), count with `list_ci` or `list_records` instead: `fields="sys_id"` (`fields="sys_id,sys_class_name"` for a count per class), `limit=1000`, and page with `offset` until a page comes back empty. Say that the numbers were counted from readable rows.

1. **Totals.** CIs per class, and the active hardware that most checks score:
   ```
   aggregate_records(table_name="cmdb_ci", group_by="sys_class_name")
   aggregate_records(table_name="cmdb_ci_hardware", query="install_status=1^operational_status=1", group_by="sys_class_name")
   ```
   `group_by="sys_class_name"` counts each exact class. A class table such as `cmdb_ci_hardware` holds the class and all its subclasses; on `cmdb_ci`, the condition `sys_class_nameINSTANCEOF<class>` does the same. `install_status=1` is Installed and `operational_status=1` is Operational: the set that ServiceNow's CMDB Data Foundations dashboard scores. Put `cmdb_ci_vm_instance`, `cmdb_ci_appl` or any other class in place of `cmdb_ci_hardware` the same way.

2. **Duplicates tagged by IRE.** The Identification and Reconciliation Engine (IRE) sets `duplicate_of` on a duplicate CI to point at the main CI, when `glide.identification_engine.skip_duplicates` is on (the default) and the set is under its threshold (5 by default). It creates a de-duplication task in every case, so count `reconcile_duplicate_task` too. The field stays set after remediation, so a set CI is not always an open problem; IRE clears it when IRE processing updates another attribute of the CI. Count the unhandled ones as the CMDB Data Foundations dashboard does, on active CIs, and the ever-tagged total for context:
   ```
   aggregate_records(table_name="cmdb_ci_hardware", query="install_status=1^operational_status=1^duplicate_ofISNOTEMPTY", group_by="sys_class_name")
   aggregate_records(table_name="cmdb_ci_vm_instance", query="install_status=1^operational_status=1^duplicate_ofISNOTEMPTY")
   aggregate_records(table_name="cmdb_ci", query="duplicate_ofISNOTEMPTY", group_by="sys_class_name")
   list_ci(class_name="cmdb_ci", query="duplicate_ofISNOTEMPTY", fields="name,sys_class_name,duplicate_of,install_status", limit=5)
   list_records(table_name="reconcile_duplicate_task", query="active=true", fields="number,state,active", limit=5)
   ```
   The last call lists the open de-duplication tasks that IRE groups each set of duplicates into.

3. **The same name within a class.** These are duplicates IRE never saw, for example CIs loaded by an import that skipped the identification rules:
   ```
   aggregate_records(table_name="cmdb_ci_server", query="nameISNOTEMPTY", group_by="name", having="count^name^>^1")
   list_ci(class_name="cmdb_ci_server", query="name=<name>", fields="name,sys_class_name,serial_number,ip_address,discovery_source,sys_created_on", limit=5)
   ```
   Each group is one repeated name, and its count is how many CIs share it; the counts added up give the CIs involved. `having` takes the Aggregate API's form `aggregate^field^operator^value`. Run it per class: the same name on a server and on an application that runs there is usually not a duplicate. Without the Aggregate API, list the names in order and look for neighbouring rows with the same name: `list_records(table_name="cmdb_ci_server", query="nameISNOTEMPTY", fields="name", order_by="name", limit=1000)` (`list_ci` takes no `order_by`).

4. **Stale CIs.** Two fields, two meanings:
   - `sys_updated_on` is the last change to the record by anyone (a person, an import, a script). The CMDB Data Foundations dashboard counts installed, operational hardware not updated in 90 days as stale.
   - `last_discovered` ("Most recent discovery") is the last time a discovery source (Discovery, a Service Graph connector) reported the CI. Empty means never discovered: created by hand or imported.
   ```
   aggregate_records(table_name="cmdb_ci_hardware", query="install_status=1^operational_status=1^sys_updated_onRELATIVELT@dayofweek@ago@90", group_by="sys_class_name")
   aggregate_records(table_name="cmdb_ci_hardware", query="install_status=1^operational_status=1^last_discoveredRELATIVELT@dayofweek@ago@90")
   aggregate_records(table_name="cmdb_ci_hardware", query="install_status=1^operational_status=1^last_discoveredISEMPTY")
   list_ci(class_name="cmdb_ci_hardware", query="install_status=1^operational_status=1^sys_updated_onRELATIVELT@dayofweek@ago@90", fields="name,sys_class_name,sys_updated_on,last_discovered,discovery_source", limit=5)
   ```
   `RELATIVELT` skips empty dates, so never-discovered CIs need their own count (the third call). `sys_updated_on<javascript:gs.beginningOfLast90Days()` gives the same 90-day cut-off as a date helper. When the class has a staleness rule (`cmdb_health_staleness_rule`, workflow 3), use its window instead of 90 days.

5. **Orphans: CIs with no relationship in either direction.** The Table API accepts a related-list condition, `RLQUERY<table>.<reference field>,<operator><count>^ENDRLQUERY`:
   ```
   list_ci(class_name="cmdb_ci", query="sys_class_nameINSTANCEOFcmdb_ci_server^RLQUERYcmdb_rel_ci.parent,=0^ENDRLQUERY", fields="sys_id,name,sys_class_name", limit=1000)
   list_ci(class_name="cmdb_ci", query="sys_class_nameINSTANCEOFcmdb_ci_server^RLQUERYcmdb_rel_ci.child,=0^ENDRLQUERY", fields="sys_id,name,sys_class_name", limit=1000)
   ```
   The first call lists the CIs that are never a parent, the second the CIs that are never a child. A CI in both lists is an orphan, so intersect the `sys_id`s. Keep the two calls separate: when one query holds two RLQUERY blocks, only the first is applied. Keep the block to the count, too: conditions inside it were ignored. Check one orphan with `get_ci_relationships(sys_id="<ci_sys_id>")`, which should return a count of 0. Some classes are meant to stand alone; the class's `cmdb_health_orphan_rule` (workflow 3) says which.

6. **Broken relationships** in `cmdb_rel_ci`:
   ```
   aggregate_records(table_name="cmdb_rel_ci")
   aggregate_records(table_name="cmdb_rel_ci", query="parentISEMPTY^ORchildISEMPTY^ORtypeISEMPTY")
   aggregate_records(table_name="cmdb_rel_ci", query="parent.sys_class_nameISEMPTY^ORchild.sys_class_nameISEMPTY")
   list_records(table_name="cmdb_rel_ci", query="parent.sys_class_nameISEMPTY^ORchild.sys_class_nameISEMPTY", fields="parent,child,type,sys_updated_on", limit=5)
   ```
   The second call finds empty ends or an empty type. The third finds ends that point at a CI that no longer exists; the CMDB Data Foundations dashboard counts these as its "orphan CIs".

7. **Missing key fields per class.** One count per field, over the same class and status, so each field gets its own percentage:
   ```
   aggregate_records(table_name="cmdb_ci_server", query="install_status=1")
   aggregate_records(table_name="cmdb_ci_server", query="install_status=1^support_groupISEMPTY")
   aggregate_records(table_name="cmdb_ci_server", query="install_status=1^serial_numberISEMPTY")
   list_ci(class_name="cmdb_ci_server", query="install_status=1^support_groupISEMPTY", fields="name,support_group,managed_by,location", limit=5)
   ```
   Repeat the count for each key field of the class: `name`, `serial_number`, `ip_address` (servers and network gear), `support_group`, `managed_by`, `owned_by`, `location` and `model_id`. A field that is empty on every row may be unused on this instance, or hidden from this identity: check the sample's warning before calling it a gap.

8. **Locations, models and assets** (the CSDM Foundation data):
   ```
   aggregate_records(table_name="cmn_location", query="parentISEMPTY")
   list_records(table_name="cmn_location", query="parentISEMPTY", fields="name,cmn_location_type,parent", limit=5)
   aggregate_records(table_name="cmdb_ci", query="install_status=1^operational_status=1^locationISNOTEMPTY^location.parentISEMPTY")
   aggregate_records(table_name="cmdb_model", query="status=In Production^ownerISEMPTY", group_by="sys_class_name")
   aggregate_records(table_name="cmdb_model", query="manufacturerISEMPTY", group_by="sys_class_name")
   aggregate_records(table_name="alm_hardware", query="install_status!=7^model_category.cmdb_ci_classISNOTEMPTY^ciISEMPTY")
   aggregate_records(table_name="cmdb_ci_hardware", query="install_status=1^assetISEMPTY", group_by="sys_class_name")
   ```
   - Only the top of the location tree (a region or a country) should have no `parent`; `cmn_location_type` gives the level where it is set. The third call counts the CIs that fail the CSDM metric "Locations with Parents": active CIs whose location has no parent.
   - On `cmdb_model`, `owner` is a user and `manufacturer` a company. The CSDM metric counts models in production that have an owner.
   - `alm_hardware.ci` links an asset to its CI. Count only assets whose model category creates CIs (`model_category.cmdb_ci_class` is set), and leave out retired ones (`install_status=7`). The last call is the other direction: hardware CIs with no `asset`. It matters only where Asset Management is in use.

9. **Report** each check as count / total = percent, per class where that helps, with a few examples by name and class. Say which checks were not assessable (403, 401) and which returned 0 on both the count and the total (empty or hidden: say you can't tell). Recommend fixes, such as the de-duplication tasks in CMDB Workspace, a staleness rule per class, or owners for models, but make none.

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
