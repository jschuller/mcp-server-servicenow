# ServiceNow Encoded Query Syntax

An encoded query is a list of conditions in the form `<field><operator><value>`, joined with `^`. Every operator below was checked against a Brazil instance through the Table API.

## Comparison Operators

| Operator | Meaning | Example |
|----------|---------|---------|
| `=` | Equals | `active=true` |
| `!=` | Not equals | `state!=6` |
| `LIKE` | Contains | `short_descriptionLIKEnetwork` |
| `NOT LIKE` | Does not contain | `short_descriptionNOT LIKEtest` |
| `STARTSWITH` | Starts with | `numberSTARTSWITHINC` |
| `ENDSWITH` | Ends with | `nameENDSWITHserver` |
| `IN` | In list (comma-separated) | `stateIN1,2,3` |
| `NOT IN` | Not in list | `stateNOT IN6,7` |
| `ISEMPTY` | Field is empty | `assigned_toISEMPTY` |
| `ISNOTEMPTY` | Field is not empty | `assigned_toISNOTEMPTY` |
| `INSTANCEOF` | Is this class or a subclass | `sys_class_nameINSTANCEOFcmdb_ci_server` |

## Numeric and Field Comparisons

| Operator | Meaning | Example |
|----------|---------|---------|
| `>` `>=` `<` `<=` | Greater / less than | `priority<=2` |
| `BETWEEN` | Inclusive range, ends joined with `@` | `priorityBETWEEN1@2` |
| `SAMEAS` | Equals another field | `opened_bySAMEAScaller_id` |
| `NSAMEAS` | Differs from another field | `opened_byNSAMEAScaller_id` |
| `GT_FIELD` | Greater than another field | `sys_updated_onGT_FIELDsys_created_on` |
| `LT_FIELD` | Less than another field | `sys_updated_onLT_FIELDsys_created_on` |

## Dates

**Relative to now.** These need no script: `<field><OP>@<unit>@ago@<n>`.

| Operator | Meaning | Example |
|----------|---------|---------|
| `RELATIVEGT` | After N units ago | `opened_atRELATIVEGT@dayofweek@ago@30` (last 30 days) |
| `RELATIVEGE` | At or after | `opened_atRELATIVEGE@hour@ago@4` |
| `RELATIVELT` | Before N units ago | `sys_updated_onRELATIVELT@month@ago@6` (untouched for 6 months) |
| `RELATIVELE` | At or before | `opened_atRELATIVELE@year@ago@1` |
| `RELATIVEEE` | On that day | `opened_atRELATIVEEE@dayofweek@ago@1` |

Units are `minute`, `hour`, `dayofweek` (days), `month` and `year`. Use `dayofweek` for days: `@day@` silently matched nothing.

**Ranges, as the list UI writes them.** The two ends are separated by `@`:

| Form | Example |
|------|---------|
| On a day | `opened_atON2026-10-01@javascript:gs.dateGenerate('2026-10-01','start')@javascript:gs.dateGenerate('2026-10-01','end')` |
| On a named period | `opened_atONToday@javascript:gs.beginningOfToday()@javascript:gs.endOfToday()` |
| Not on a period | `opened_atNOTONLast 6 months@javascript:gs.beginningOfLast6Months()@javascript:gs.endOfLast6Months()` |
| Between two dates | `opened_atBETWEENjavascript:gs.dateGenerate('2026-10-01','00:00:00')@javascript:gs.dateGenerate('2026-10-07','23:59:59')` |
| Between relative days | `opened_atBETWEENjavascript:gs.daysAgoStart(14)@javascript:gs.daysAgoEnd(7)` |

How the helpers behave:
- `gs.dateGenerate('<yyyy-mm-dd>', 'start' | 'end' | '<hh:mm:ss>')` reads the date in the caller's time zone.
- The other date helpers work as single bounds too:
  - `sys_created_on>=javascript:gs.daysAgoStart(1)` (since the start of yesterday);
  - `gs.beginningOfLastMonth()`;
  - `gs.monthsAgoStart(1)`.

## Server-side script in queries

This server accepts only GlideSystem **date helpers** in `javascript:` values:
- `gs.daysAgo*`, `gs.hoursAgo*`, `gs.minutesAgo*`, `gs.monthsAgo*`, `gs.quartersAgo*`, `gs.yearsAgo*`;
- `gs.beginningOf*`, `gs.endOf*`, `gs.now*`;
- `gs.dateGenerate(...)` with a literal date and `'start'`, `'end'` or a literal time.

Each helper must end the value: at `^`, at the `@` between the two ends of a range, or at the end of the query. Anything else is rejected with "Query rejected: unsafe javascript:". That covers `gs.getUserName()`, `GlideRecord`, `;` and `new`, and also `gs.datePart`, so write date parts as a range instead. Prefer the RELATIVE operators where they fit.

## Join Operators

| Operator | Meaning | Example |
|----------|---------|---------|
| `^` | AND | `active=true^priority=1` |
| `^OR` | OR (binds to the condition before it) | `priority=1^ORpriority=2` |
| `^NQ` | New query: the union of two queries | `priority=1^NQpriority=2` |

## Order Operators

| Operator | Meaning | Example |
|----------|---------|---------|
| `ORDERBY` | Sort ascending | `active=true^ORDERBYnumber` |
| `ORDERBYDESC` | Sort descending | `active=true^ORDERBYDESCsys_created_on` |

## Pitfalls: conditions that are ignored, not rejected

- **An operator the instance doesn't recognise is dropped.** You get the unfiltered rows. Observed: `opened_atFOOBAR7` returned every incident.
- **A condition on a field the identity can't read is ignored or refused,** depending on the field's ACL:
  - ignored: `caused_byISEMPTY` and `caused_byISNOTEMPTY` returned the same rows;
  - refused: a 403 "Field(s) present in the query do not have permission to be read".

  Request every field you filter on in `fields=`. If the field is hidden, `list_records` warns that it is missing from every row.
- **When a filter is suspicious, compare counts.** Run it once without the condition; if the counts match, the condition did nothing.
- **A short page doesn't mean the end.** The limit is applied before ACLs remove rows, so keep paging with `offset`.

## Common Patterns

```
# Active P1 incidents assigned to someone, newest first
active=true^priority=1^assigned_toISNOTEMPTY^ORDERBYDESCsys_created_on

# Incidents opened in the last 7 days
opened_atRELATIVEGT@dayofweek@ago@7

# Servers, including every server subclass
sys_class_nameINSTANCEOFcmdb_ci_server

# Open incidents for a specific CI
active=true^cmdb_ci=<sys_id>

# Records updated today
sys_updated_onONToday@javascript:gs.beginningOfToday()@javascript:gs.endOfToday()
```

## Sources
- [MobileGlideRecord - Scoped](https://www.servicenow.com/docs/r/brazil/api-reference/MobileGlideRecordScopedAPI.html) · [source](https://github.com/ServiceNow/ServiceNowDocs/blob/753a7f0e8fac/markdown/api-reference/MobileGlideRecordScopedAPI.md)
- [GlideSystem - Global](https://www.servicenow.com/docs/r/brazil/api-reference/server-api-reference/c_GlideSystemAPI.html) · [source](https://github.com/ServiceNow/ServiceNowDocs/blob/753a7f0e8fac/markdown/api-reference/server-api-reference/c_GlideSystemAPI.md)
- [Table API](https://www.servicenow.com/docs/r/brazil/api-reference/rest-apis/c_TableAPI.html) · [source](https://github.com/ServiceNow/ServiceNowDocs/blob/753a7f0e8fac/markdown/api-reference/rest-apis/c_TableAPI.md)
- [Enforce field ACLs for inbound query requests](https://www.servicenow.com/docs/r/brazil/platform-security/instance-security-hardening-settings/sc-enforce-field-acls-for-inbound-query-requests.html) · [source](https://github.com/ServiceNow/ServiceNowDocs/blob/753a7f0e8fac/markdown/platform-security/instance-security-hardening-settings/sc-enforce-field-acls-for-inbound-query-requests.md)
