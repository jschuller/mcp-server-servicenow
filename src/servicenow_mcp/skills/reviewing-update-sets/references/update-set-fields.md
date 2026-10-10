# Update Set Reference

## Table of Contents

- [Update Set States](#update-set-states)
- [Customer Update Types](#customer-update-types)
- [Risk Categories](#risk-categories)
- [Pre-Promotion Checklist Fields](#pre-promotion-checklist-fields)
- [Useful Encoded Queries](#useful-encoded-queries)

---

## Update Set States

| State | Value | Description |
|-------|-------|-------------|
| In Progress | `in progress` | Actively collecting changes; can be set as current |
| Complete | `complete` | Finalized; ready for promotion review |
| Ignore | `ignore` | Excluded from promotion pipeline |

Only update sets in `complete` state should be promoted.

## Customer Update Types

Changes stored in `sys_update_xml` — the `type` field indicates what was modified.

| Type | Table | Risk Level | Description |
|------|-------|------------|-------------|
| Business Rule | `sys_script` | Medium | Server-side logic triggered by record operations |
| Client Script | `sys_script_client` | Low | Browser-side logic on forms |
| UI Policy | `sys_ui_policy` | Low | Form field visibility/mandatory/read-only rules |
| UI Action | `sys_ui_action` | Low | Buttons, links, context menu items |
| ACL | `sys_security_acl` | **High** | Access control rules — security impact |
| Script Include | `sys_script_include` | **High** | Shared server-side libraries — wide blast radius |
| Scheduled Job | `sysauto_script` | Medium | Background automation — runs unattended |
| UI Page | `sys_ui_page` | Low | Custom portal/UI pages |
| Table/Column | `sys_dictionary` | **High** | Schema changes — data model impact |
| Style Sheet | `sys_ui_style` | Low | CSS customizations |
| System Property | `sys_properties` | **High** | Global configuration — affects entire instance |
| Notification | `sysevent_email_action` | Medium | Email notification rules |
| Workflow | `wf_workflow` | Medium | Automated process flows |
| Flow | `sys_hub_flow` | Medium | Flow Designer flows |

## Risk Categories

Flag these change types for extra review before promotion:

### High Risk
- **ACL modifications** — Can inadvertently grant or revoke access to sensitive data
- **Script Includes** — Shared libraries used by multiple business rules and flows; a bug affects many areas
- **Table/Column schema changes** — Alters the data model; can break integrations, reports, and existing records
- **System Properties** — Global configuration that affects the entire instance behavior

### Medium Risk
- **Business Rules** — Server-side logic that runs on every insert/update/delete; can cause cascading issues
- **Scheduled Jobs** — Run unattended in the background; failures may go unnoticed
- **Notifications** — Can spam users or expose data in emails if misconfigured
- **Workflows/Flows** — Automated processes that may trigger downstream actions

### Low Risk
- **Client Scripts** — Browser-only; limited blast radius
- **UI Policies** — Form-level changes; easily reversible
- **UI Actions** — Button/link additions; minimal side effects
- **UI Pages** — Custom pages; isolated scope
- **Style Sheets** — Visual-only changes

## Pre-Promotion Checklist Fields

| Check | Field/Query | Pass Criteria |
|-------|------------|---------------|
| State is complete | `state` on update set record | `state == "complete"` |
| No Default set entries | `update_set.name` in changes | No changes where set name is "Default" |
| No test artifacts | `name` field in changes | No names containing "test", "debug", "temp" |
| No personal artifacts | `sys_created_by` in changes | All changes by expected developer(s) |
| High-risk items reviewed | `type` field in changes | All ACL, Script Include, schema, property changes flagged |

## Useful Encoded Queries

```
# Complete update sets by a specific developer
state=complete^sys_created_by=<developer_username>

# In-progress update sets modified recently
state=in progress^sys_updated_on>=javascript:gs.daysAgoStart(7)

# Changes that are scripts (business rules or script includes)
type=sys_script^ORtype=sys_script_include

# ACL changes only
type=sys_security_acl

# Changes in a specific update set (use in sys_update_xml table)
update_set=<update_set_sys_id>

# Update sets with "release" in the name
nameLIKErelease
```
