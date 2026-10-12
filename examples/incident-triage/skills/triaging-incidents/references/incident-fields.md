# Incident Reference

## Table of Contents

- [Priority Matrix](#priority-matrix)
- [Incident States](#incident-states)
- [Common Categories](#common-categories)
- [Key Fields for Triage](#key-fields-for-triage)
- [Encoded Query Patterns](#encoded-query-patterns)

---

## Priority Matrix

Priority is calculated from Impact x Urgency. ServiceNow uses this default matrix:

| | Urgency 1 (High) | Urgency 2 (Medium) | Urgency 3 (Low) |
|---|---|---|---|
| **Impact 1 (High)** | P1 — Critical | P2 — High | P3 — Moderate |
| **Impact 2 (Medium)** | P2 — High | P3 — Moderate | P4 — Low |
| **Impact 3 (Low)** | P3 — Moderate | P4 — Low | P5 — Planning |

**Impact guidelines:**
- **1 (High):** Enterprise-wide or multiple departments affected
- **2 (Medium):** Single department or large user group affected
- **3 (Low):** Individual user or small group affected

**Urgency guidelines:**
- **1 (High):** Critical business process stopped, no workaround
- **2 (Medium):** Business process degraded, workaround available
- **3 (Low):** Minor inconvenience, workaround available

## Incident States

| Value | Label | Description |
|-------|-------|-------------|
| 1 | New | Just created, not yet assigned or acknowledged |
| 2 | In Progress | Assigned and being worked on |
| 3 | On Hold | Waiting for customer, vendor, or third party |
| 6 | Resolved | Fix applied, awaiting confirmation |
| 7 | Closed | Confirmed resolved, ticket closed |
| 8 | Canceled | No longer needed or created in error |

**Active incidents:** States 1, 2, 3 (`active=true` or `state!=6^state!=7^state!=8`)

## Common Categories

| Category | Subcategories (examples) |
|----------|------------------------|
| Software | Operating System, Application Software, Email |
| Hardware | CPU, Disk, Memory, Monitor, Peripheral |
| Network | DNS, Firewall, IP Address, VPN, Wireless |
| Database | DB2, Oracle, SQL Server, Performance |
| Inquiry / Help | Password Reset, How To, Status Request |
| Request | Access, Hardware, Software, Account |

## Key Fields for Triage

| Field | Type | Description |
|-------|------|-------------|
| `short_description` | String | One-line summary (mandatory) |
| `description` | String | Detailed description of the issue |
| `impact` | Integer (1-3) | How many users/services affected |
| `urgency` | Integer (1-3) | How quickly a resolution is needed |
| `priority` | Integer (1-5) | Auto-calculated from impact x urgency |
| `category` | String | High-level classification |
| `subcategory` | String | Detailed classification within category |
| `assignment_group` | Reference | Team responsible for resolution |
| `assigned_to` | Reference | Individual working the incident |
| `cmdb_ci` | Reference | Affected configuration item |
| `caller_id` | Reference | Person who reported the incident |
| `state` | Integer | Current state (see Incident States) |
| `opened_at` | DateTime | When the incident was created |
| `resolved_at` | DateTime | When the incident was resolved |
| `closed_at` | DateTime | When the incident was closed |
| `sla_due` | DateTime | SLA target date/time |
| `made_sla` | Boolean | Whether the SLA was met |
| `close_code` | String | Resolution classification (Solved, Workaround, etc.) |
| `close_notes` | String | Description of the resolution |

## Encoded Query Patterns

```
# Open P1 incidents (critical)
priority=1^state!=6^state!=7^state!=8

# Open P1 and P2 incidents
priority<=2^active=true

# Active incidents for a specific assignment group
active=true^assignment_group=<group_sys_id>

# Incidents created in the last 24 hours
sys_created_on>=javascript:gs.daysAgoStart(1)

# Incidents created in the last 7 days
sys_created_on>=javascript:gs.daysAgoStart(7)

# Incidents for a specific CI
cmdb_ci=<ci_sys_id>^active=true

# Unassigned incidents
active=true^assigned_toISEMPTY

# Incidents breaching SLA
active=true^sla_due<javascript:gs.daysAgoEnd(0)

# Incidents by category
category=Software^active=true

# Resolved but not closed (pending confirmation)
state=6

# Recently resolved incidents (last 7 days)
state=6^ORstate=7^resolved_at>=javascript:gs.daysAgoStart(7)
```
