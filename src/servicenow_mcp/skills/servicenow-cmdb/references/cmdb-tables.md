# CMDB Reference Tables

## Table of Contents

- [CMDB Health KPIs](#cmdb-health-kpis)
- [Health Tables](#health-tables)
- [CSDM Core Classes](#csdm-core-classes)
- [Common CI Base Classes](#common-ci-base-classes)
- [Data Quality Checks](#data-quality-checks)
- [Encoded Query Syntax](#encoded-query-syntax)

---

## CMDB Health KPIs

| Category | KPI | Description |
|----------|-----|-------------|
| Correctness | Orphan CIs | CIs with no relationships (isolated nodes) |
| Correctness | Staleness | CIs not updated by discovery within expected window |
| Correctness | Duplicates | Multiple CIs representing the same physical/logical entity |
| Completeness | Required fields | Percentage of CIs with all mandatory fields populated |
| Compliance | Audit-based | CIs passing configured audit rules |
| Relationships | Relationship health | CIs with valid, non-circular relationship chains |

## Health Tables

Installed with CMDB Health (`com.snc.cmdb`); see ServiceNow's [components installed with CMDB Health](https://www.servicenow.com/docs/r/brazil/servicenow-platform/configuration-management-database-cmdb/r_TablesInstalledCMDBHealth.html). Readable with `itil` + `snc_read_only`.

| Table | Purpose |
|-------|---------|
| `cmdb_health_scorecard` | Health scores over time: the newest rows are current, older ones history |
| `cmdb_health_result` | What the most recent processing cycle found |
| `cmdb_health_metric` | Each KPI and metric: whether it is on, its failure threshold and other settings |
| `cmdb_health_metric_status` | Processing state of each KPI and metric (completed, hit its failure limit, timed out) |
| `cmdb_health_staleness_rule` | Per class: how long a CI may go without an update before it counts as stale |
| `cmdb_health_orphan_rule` | Per class: when a CI counts as orphaned |
| `cmdb_health_config` | Inclusion rules: which classes are scored |

## CSDM Core Classes

| CSDM Layer | Class | Table Name |
|------------|-------|------------|
| Business Service | Service | `cmdb_ci_service_business` |
| Technical Service | Service | `cmdb_ci_service_technical` |
| Application Service | Service (auto-discovered) | `cmdb_ci_service_auto` |
| Business Capability | Capability | `cmdb_ci_business_capability` |
| Business Application | Application | `cmdb_ci_business_app` |
| Information Object | Data entity | `cmdb_ci_information_object` |

## Common CI Base Classes

| Class | Table Name | Typical Fields |
|-------|------------|---------------|
| Server | `cmdb_ci_server` | `ip_address`, `os`, `ram`, `cpu_count`, `disk_space` |
| Computer | `cmdb_ci_computer` | `os`, `os_version`, `cpu_type`, `ram` |
| VM Instance | `cmdb_ci_vm_instance` | `object_id`, `vcenter_ref`, `host_name` |
| Network Gear | `cmdb_ci_netgear` | `ip_address`, `firmware_version`, `device_type` |
| Database Instance | `cmdb_ci_db_instance` | `type`, `version`, `port`, `host` |
| Application | `cmdb_ci_appl` | `version`, `install_directory`, `running_process` |
| Cloud Service Account | `cmdb_ci_cloud_service_account` | `account_id`, `cloud_provider` |

## Data Quality Checks

The fields behind workflow 4 in SKILL.md, and how ServiceNow's dashboards define the same checks. The filters in workflow 4 were run with `list_ci` and `list_records` on a Brazil developer instance, with an `itil` + `snc_read_only` identity. The Aggregate API was refused there (401 under API-key auth), so the `group_by` and `having` forms follow the Aggregate API documentation and were not run.

| Check | Field or condition | What it means |
|-------|--------------------|---------------|
| Duplicate tagged by IRE | `duplicate_ofISNOTEMPTY` | IRE found the CI to match another one and points `duplicate_of` at the main CI, when `glide.identification_engine.skip_duplicates` is on (the default) and the set is under its threshold (5 by default); otherwise only a de-duplication task records the set. The main CI's own `duplicate_of` is empty. It stays set on the duplicates after remediation; IRE clears it when IRE processing updates another attribute of the CI. Unhandled duplicates are the active ones (`install_status=1^operational_status=1`). Upgrades from before New York set it to "Unknown" when the main CI is not known. |
| De-duplication task | `reconcile_duplicate_task` | One task per set of duplicates, which is remediated in CMDB Workspace |
| Not updated | `sys_updated_on` | The last change to the record by anyone: a person, an import, a script |
| Not discovered | `last_discovered` ("Most recent discovery") | The last time a discovery source reported the CI. Empty: never discovered |
| No relationships | `RLQUERYcmdb_rel_ci.parent,=0^ENDRLQUERY` and the same on `child` | The CI is never a parent, or never a child, in `cmdb_rel_ci` |
| Broken relationship | `parent.sys_class_nameISEMPTY^ORchild.sys_class_nameISEMPTY` | One end points at a CI that no longer exists |
| Location without parent | `cmn_location.parentISEMPTY` | Right only for the top of the tree; `cmn_location_type` gives the level |
| Model without owner | `cmdb_model.ownerISEMPTY` | `owner` is a user; `manufacturer` is a company |
| Asset without CI | `alm_hardware.ciISEMPTY` | Only a gap when `model_category.cmdb_ci_class` is set and the asset isn't retired (`install_status=7`) |

### How the dashboards define them

- **CMDB Data Foundations dashboard:** scores Hardware (`cmdb_ci_hardware`) and VM Instance (`cmdb_ci_vm_instance`) CIs that are Installed (`install_status=1`) and Operational (`operational_status=1`):
  - "Active CIs Updated in Last 90 days": stale means not updated for 90 days or more.
  - "Handled Duplicate CIs": counts installed, operational CIs with `duplicate_of` set; the score drops to 0 above 200 unhandled duplicates.
  - "CIs with Relationships to Parent and Child": calls a relationship orphaned when `parent.sys_class_name` or `child.sys_class_name` is empty. That is a broken relationship in workflow 4, not a CI without relationships.
- **CMDB Health:** its staleness rules default to 60 days (`cmdb_health_staleness_rule`), and its orphan rules are set per class.
- **CSDM Data Foundations dashboard:**
  - "Locations with Parents": active CIs whose location has a parent.
  - "Named Product Models with Product Owners": `cmdb_model` rows in production with a name and an `owner`.

### Query behaviour observed on a Brazil instance

- **RLQUERY applies to the Table API, but only one block per query.** `RLQUERYcmdb_rel_ci.parent,=0^ENDRLQUERY` and `,>=1` returned two different sets of CIs. With two blocks in one query, only the first was applied. Conditions inside a block (`RLQUERYsys_user_has_role.user,>=1^role.name=<role>^ENDRLQUERY`) were ignored: a role name that does not exist matched the same users.
- **`RELATIVELT` skips empty dates:** `last_discoveredRELATIVELT@dayofweek@ago@90` doesn't count never-discovered CIs. Count `last_discoveredISEMPTY` separately.
- **`gs.beginningOfLast90Days()` and `RELATIVELT@dayofweek@ago@90` gave the same rows on this instance.** Its data had no updates near the cut-off, so this does not prove they cut at the same moment.
- **`having` takes the form `aggregate^field^operator^value`** (`count^name^>^1`), as the Aggregate API documents it.

## Encoded Query Syntax

### Operators

| Operator | Meaning | Example |
|----------|---------|---------|
| `=` | Equals | `state=1` |
| `!=` | Not equals | `state!=7` |
| `LIKE` | Contains | `nameLIKEweb` |
| `STARTSWITH` | Starts with | `nameSTARTSWITHprod` |
| `ENDSWITH` | Ends with | `nameENDSWITHdb` |
| `IN` | In list | `stateIN1,2,3` |
| `ISEMPTY` | Field is empty | `ip_addressISEMPTY` |
| `ISNOTEMPTY` | Field is not empty | `ip_addressISNOTEMPTY` |
| `INSTANCEOF` | This class or a subclass | `sys_class_nameINSTANCEOFcmdb_ci_server` |
| `ORDERBY` | Sort ascending | `ORDERBY` field |
| `ORDERBYDESC` | Sort descending | `ORDERBYDESC` field |

### Date Operators

| Expression | Meaning |
|-----------|---------|
| `javascript:gs.daysAgoStart(7)` | 7 days ago (start of day) |
| `javascript:gs.daysAgoEnd(0)` | End of today |
| `javascript:gs.monthsAgoStart(1)` | Start of last month |
| `javascript:gs.beginningOfLastWeek()` | Beginning of last week |
| `javascript:gs.beginningOfLast90Days()` | 90 days ago (start of day) |
| `RELATIVELT@dayofweek@ago@90` | Before 90 days ago, without script (`sys_updated_onRELATIVELT@dayofweek@ago@90`) |

### Chaining

| Connector | Meaning | Example |
|-----------|---------|---------|
| `^` | AND | `active=true^priority=1` |
| `^OR` | OR | `state=1^ORstate=2` |
| `^NQ` | New query (OR group) | `state=1^NQstate=2^priority=1` |

## Sources
- [Base system roles](https://www.servicenow.com/docs/r/brazil/platform-administration/user-administration/r_BaseSystemRoles.html) · [source](https://github.com/ServiceNow/ServiceNowDocs/blob/753a7f0e8fac/markdown/platform-administration/user-administration/r_BaseSystemRoles.md)
- [Combined CMDB release notes for upgrades from Zurich to Brazil](https://www.servicenow.com/docs/r/brazil/delta-zurich-brazil/brazil-zurich-configurationmanagementdatabasecmdb-release-notes.html) · [source](https://github.com/ServiceNow/ServiceNowDocs/blob/753a7f0e8fac/markdown/delta-zurich-brazil/brazil-zurich-configurationmanagementdatabasecmdb-release-notes.md)
- [Detecting duplicate CIs](https://www.servicenow.com/docs/r/brazil/servicenow-platform/configuration-management-database-cmdb/id-detect-dup-ci.html) · [source](https://github.com/ServiceNow/ServiceNowDocs/blob/753a7f0e8fac/markdown/servicenow-platform/configuration-management-database-cmdb/id-detect-dup-ci.md)
- [Duplicate CIs remediation](https://www.servicenow.com/docs/r/brazil/servicenow-platform/configuration-management-database-cmdb/de-duplication-tasks.html) · [source](https://github.com/ServiceNow/ServiceNowDocs/blob/753a7f0e8fac/markdown/servicenow-platform/configuration-management-database-cmdb/de-duplication-tasks.md)
- [CMDB Data Foundations dashboard](https://www.servicenow.com/docs/r/brazil/servicenow-platform/configuration-management-database-cmdb/cmdb-data-foundations-dashboard.html) · [source](https://github.com/ServiceNow/ServiceNowDocs/blob/753a7f0e8fac/markdown/servicenow-platform/configuration-management-database-cmdb/cmdb-data-foundations-dashboard.md)
- [Configure the CSDM Data Foundations dashboard](https://www.servicenow.com/docs/r/brazil/servicenow-platform/common-service-data-model-csdm/csdm-foundations-dashboard.html) · [source](https://github.com/ServiceNow/ServiceNowDocs/blob/753a7f0e8fac/markdown/servicenow-platform/common-service-data-model-csdm/csdm-foundations-dashboard.md)
- [Domain separation and CMDB Identification and Reconciliation](https://www.servicenow.com/docs/r/brazil/servicenow-platform/configuration-management-database-cmdb/domain-separation-identification-reconciliation.html) · [source](https://github.com/ServiceNow/ServiceNowDocs/blob/753a7f0e8fac/markdown/servicenow-platform/configuration-management-database-cmdb/domain-separation-identification-reconciliation.md)
- [CMDB Health metrics](https://www.servicenow.com/docs/r/brazil/servicenow-platform/configuration-management-database-cmdb/r_CMDBHealthMetrics.html) · [source](https://github.com/ServiceNow/ServiceNowDocs/blob/753a7f0e8fac/markdown/servicenow-platform/configuration-management-database-cmdb/r_CMDBHealthMetrics.md)
- [Aggregate API](https://www.servicenow.com/docs/r/brazil/api-reference/rest-apis/c_AggregateAPI.html) · [source](https://github.com/ServiceNow/ServiceNowDocs/blob/753a7f0e8fac/markdown/api-reference/rest-apis/c_AggregateAPI.md)
- [CMDB MCP Server tools reference](https://www.servicenow.com/docs/r/brazil/servicenow-platform/now-assist-for-configuration-management-database-cmdb/na-cmdb-mcp-server-ref.html) · [source](https://github.com/ServiceNow/ServiceNowDocs/blob/753a7f0e8fac/markdown/servicenow-platform/now-assist-for-configuration-management-database-cmdb/na-cmdb-mcp-server-ref.md)
