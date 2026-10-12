---
name: assessing-change-impact
description: "Assessing what a ServiceNow change request touched and what followed it: affected CIs, other changes on the same CIs in an overlapping window, and incidents on those CIs after the change, without trusting hidden incident-to-change links. Use this skill whenever the user asks whether a change (a CHG number) caused or broke anything, about a post-implementation review, change collisions or conflicts, or what else is scheduled on a CI, even if they do not ask for a skill."
license: MIT
metadata:
  author: mcp-server-servicenow examples
  version: "0.1.0"
  io.github.jschuller/servicenow-roles: "itil snc_read_only"
  io.github.jschuller/servicenow-tables: "change_request task_ci incident"
---

# Assessing Change Impact

Read-only evidence for a post-implementation review: what a change touched, what overlapped with it, and what broke afterwards. It finds correlation, not cause. Say so in the report, and let the people who ran the change judge.

## Tables and roles

| Table | What it gives | Readable with |
|-------|---------------|---------------|
| `change_request` | The change: CI, planned window (`start_date`, `end_date`), state, type, risk | `itil` |
| `task_ci` | Affected CIs of a task (`task`, `ci_item`) | `itil` |
| `incident` | Incidents by CI and time | `itil` |

## When access is denied

- A 403 on any of the three tables: the review is not assessable with this identity; say which table.
- **Hidden incident fields.** The direct links `incident.rfc` ("Change Request") and `incident.caused_by` ("Caused by Change") are often hidden by ACLs. A query on a hidden field is ignored, not rejected: it returns every incident. Check visibility first (workflow step 4), and fall back to the CI-and-time correlation.
- 0 rows means nothing was found with this identity. Rows may be hidden, so don't call a change clean on that alone.

## Workflow

**Progress checklist:**
```
- [ ] Read the change and its window
- [ ] List its affected CIs
- [ ] Find other changes on those CIs in an overlapping window
- [ ] Check whether incident→change links are readable
- [ ] Find incidents on those CIs after the change
- [ ] Report evidence, separating facts from judgement
```

1. Read the change:
   ```
   list_records(table_name="change_request", query="number=CHG0000076", fields="sys_id,number,short_description,cmdb_ci,start_date,end_date,state,type,risk", limit=1)
   ```
2. List its affected CIs. The main `cmdb_ci` is usually one of them, but not always:
   ```
   list_records(table_name="task_ci", query="task.number=CHG0000076", fields="ci_item,ci_item.name", limit=100)
   ```
3. **Overlapping changes on the same CI.** A change whose planned window starts before this one ends, and ends after this one starts, overlaps it. Put the change's own window into the query as `gs.dateGenerate` literals:
   ```
   list_records(table_name="change_request", query="cmdb_ci=<ci_sys_id>^start_date<javascript:gs.dateGenerate('2026-08-07','15:00:00')^end_date>javascript:gs.dateGenerate('2026-08-07','14:30:00')^number!=CHG0000076", fields="number,short_description,start_date,end_date,state", limit=50)
   ```
   Changes that list the CI only as an affected CI show up through `task_ci` instead:
   ```
   list_records(table_name="task_ci", query="ci_item=<ci_sys_id>^task.sys_class_name=change_request", fields="task.number", limit=100)
   ```
4. **Can this identity read the direct links?** Request them on a few incidents:
   ```
   list_records(table_name="incident", fields="number,rfc,caused_by", limit=5)
   ```
   If the result carries a `warning` naming `rfc` or `caused_by`, the links are hidden: skip step 5a.
5. Incidents after the change:
   - **a.** Where the links are readable: `list_records(table_name="incident", query="caused_by=<change_sys_id>^ORrfc=<change_sys_id>", fields="number,short_description,priority,opened_at", limit=50)`.
   - **b.** In every case, incidents on each affected CI opened in the 48 hours after the planned end:
     ```
     list_records(table_name="incident", query="cmdb_ci=<ci_sys_id>^opened_atBETWEENjavascript:gs.dateGenerate('2026-08-07','15:00:00')@javascript:gs.dateGenerate('2026-08-09','15:00:00')", fields="number,short_description,priority,opened_at,state", limit=50)
     ```
6. Report:
   - the change and its window;
   - its affected CIs;
   - overlapping changes, a collision risk worth raising before the next window;
   - incidents found by direct link, and separately the incidents found by CI and time.

   Label the second group as correlation. Say which checks were not assessable.

## Tips

- Dates in queries are in the caller's time zone, which matches the values the Table API returns for that identity.
- Widen the 48-hour window for changes that take effect slowly (caches, batch jobs), and say you did.
- ServiceNow's own conflict detection compares planned windows and CIs too, and also blackout and maintenance schedules. Where it runs, its results are on the change; this skill is the read-only, cross-change view.
- Leave conclusions about cause to the change owner; offer the evidence.

## Sources
- [MobileGlideRecord - Scoped](https://www.servicenow.com/docs/r/brazil/api-reference/MobileGlideRecordScopedAPI.html) · [source](https://github.com/ServiceNow/ServiceNowDocs/blob/753a7f0e8fac/markdown/api-reference/MobileGlideRecordScopedAPI.md)
- [GlideSystem - Global](https://www.servicenow.com/docs/r/brazil/api-reference/server-api-reference/c_GlideSystemAPI.html) · [source](https://github.com/ServiceNow/ServiceNowDocs/blob/753a7f0e8fac/markdown/api-reference/server-api-reference/c_GlideSystemAPI.md)
- [Associated CIs on a change request](https://www.servicenow.com/docs/r/brazil/it-service-management/change-management/c_AffectedCIsAndImpactedServices.html) · [source](https://github.com/ServiceNow/ServiceNowDocs/blob/753a7f0e8fac/markdown/it-service-management/change-management/c_AffectedCIsAndImpactedServices.md)
- [Conflict detection](https://www.servicenow.com/docs/r/brazil/it-service-management/change-management/c_ConflictDetection.html) · [source](https://github.com/ServiceNow/ServiceNowDocs/blob/753a7f0e8fac/markdown/it-service-management/change-management/c_ConflictDetection.md)
- [Create an incident](https://www.servicenow.com/docs/r/brazil/it-service-management/incident-management/create-an-incident.html) · [source](https://github.com/ServiceNow/ServiceNowDocs/blob/753a7f0e8fac/markdown/it-service-management/incident-management/create-an-incident.md)
