---
name: reviewing-sla-definitions
description: "Reviewing ServiceNow SLA, OLA and underpinning-contract definitions and how they perform: breach rates per definition, overlapping or duplicated definitions on the same table and target, and definitions that never attach. Use when the user asks about SLA breaches by definition, too many SLAs, duplicate or conflicting SLAs, SLA rationalisation, or which SLAs matter."
license: MIT
metadata:
  author: mcp-server-servicenow examples
  version: "0.1.0"
  io.github.jschuller/servicenow-roles: "itil snc_read_only"
  io.github.jschuller/servicenow-tables: "contract_sla task_sla"
---

# Reviewing SLA Definitions

Find which SLA definitions breach, which overlap, and which never run. It reads the definitions and the attached task SLAs, and changes nothing.

## Tables and roles

| Table | What it gives | Readable with |
|-------|---------------|---------------|
| `contract_sla` | Definitions: `name`, `collection` (the task table), `type` (SLA, OLA, Underpinning contract), `target` (response or resolution), `duration`, `schedule`, start/pause/stop conditions, `active` | `itil` can read the values, but on a Brazil instance it could filter only on `name` |
| `task_sla` | One row per definition attached to a task: `sla`, `task`, `stage`, `has_breached`, `business_percentage` | `itil` |

## When access is denied

- A 403 "Field(s) present in the query do not have permission to be read" on `contract_sla` means the identity can read the definitions but not filter on that field. Read them all without a query and group them yourself. There are rarely more than a few hundred.
- A 403 on `task_sla` means breach rates are not assessable with this identity.
- `aggregate_records` refused (401 under API-key auth, or 403): count from `list_records` rows instead.

## Workflow

**Progress checklist:**
```
- [ ] Read every definition
- [ ] Group them by table, target and type; flag overlaps
- [ ] Count attached task SLAs and breaches per definition
- [ ] Flag definitions that never attach
- [ ] Recommend which to merge, retire or review
```

1. Read the definitions, with no query:
   ```
   list_records(table_name="contract_sla", fields="sys_id,name,collection,type,target,duration,schedule,start_condition,stop_condition,pause_condition,active", limit=500)
   ```
   Page with `offset` until a page comes back empty.
2. Group the active definitions by `collection`, `target` and `type`. Within a group, compare start conditions:
   - **Overlap:** two definitions whose start conditions can both match the same task. Both attach, and the task is measured twice.
   - **Near-duplicates:** the same conditions with different durations or schedules. They usually mean one replaced the other without being retired.
3. Breach counts per definition. Try the aggregate first:
   ```
   aggregate_records(table_name="task_sla", group_by="sla,has_breached")
   ```
   If it is refused, read the rows and count them yourself:
   ```
   list_records(table_name="task_sla", fields="sla,sla.name,has_breached,stage", limit=500)
   ```
   Page until empty. A definition's breach rate is breached rows over all rows that are not `cancelled`.
4. Definitions with no `task_sla` rows at all never attach. Their start condition may be impossible, or the process changed.
5. Report:
   - the overlapping groups;
   - each definition with its row count and breach rate;
   - the definitions that never attach;
   - recommendations: merge overlaps, retire the unused, and look first at high breach rates on high-priority targets.

   Recommend; don't change definitions.

## Tips

- `business_percentage` over 100 means the target was missed on the definition's schedule. Very large values usually mean an old task SLA that never stopped, so check its `stage`.
- OLAs and underpinning contracts measure internal teams and suppliers. Report them apart from customer-facing SLAs.
- The ServiceNow docs describe the definition fields and the task SLA stages; cite them in your report if the audience needs the background.

## Sources
- [Create an SLA definition](https://www.servicenow.com/docs/r/brazil/it-service-management/service-level-management/t_CreateAnSLADefinition.html) · [source](https://github.com/ServiceNow/ServiceNowDocs/blob/753a7f0e8fac/markdown/it-service-management/service-level-management/t_CreateAnSLADefinition.md)
- [Task SLA table](https://www.servicenow.com/docs/r/brazil/it-service-management/service-level-management/r_TaskSLATable.html) · [source](https://github.com/ServiceNow/ServiceNowDocs/blob/753a7f0e8fac/markdown/it-service-management/service-level-management/r_TaskSLATable.md)
