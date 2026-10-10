# CMDB Reference Tables

## Table of Contents

- [CMDB Health KPIs](#cmdb-health-kpis)
- [Health Tables](#health-tables)
- [CSDM Core Classes](#csdm-core-classes)
- [Common CI Base Classes](#common-ci-base-classes)
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

| Table | Purpose |
|-------|---------|
| `cmdb_health_config` | Health dashboard configuration — defines which classes to monitor |
| `cmdb_health_audit` | Audit results — individual health check outcomes |
| `cmdb_health_result` | Aggregated health scores by class and KPI |
| `cmdb_health_kpi` | KPI definitions — what metrics are tracked |
| `cmdb_health_rule` | Health rules — specific checks (e.g., "server must have IP address") |

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
| `ORDERBY` | Sort ascending | `ORDERBY` field |
| `ORDERBYDESC` | Sort descending | `ORDERBYDESC` field |

### Date Operators

| Expression | Meaning |
|-----------|---------|
| `javascript:gs.daysAgoStart(7)` | 7 days ago (start of day) |
| `javascript:gs.daysAgoEnd(0)` | End of today |
| `javascript:gs.monthsAgoStart(1)` | Start of last month |
| `javascript:gs.beginningOfLastWeek()` | Beginning of last week |

### Chaining

| Connector | Meaning | Example |
|-----------|---------|---------|
| `^` | AND | `active=true^priority=1` |
| `^OR` | OR | `state=1^ORstate=2` |
| `^NQ` | New query (OR group) | `state=1^NQstate=2^priority=1` |
