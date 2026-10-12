---
name: analyzing-access
description: "Reviewing who holds which ServiceNow roles and explaining access denials. Lists admin and security_admin holders, roles granted directly instead of through groups, roles left on inactive or long-absent users, and diagnoses 401/403 errors, empty results and missing fields. Use when the user asks who has admin, a role or access review, least privilege, user or group hygiene, why a query returned nothing, why a field is missing, 'why did I get a 403', 'why can't user X see Y', or ACLs."
license: MIT
metadata:
  author: jschuller
  version: "2.0.0"
  io.github.jschuller/servicenow-roles: "itil snc_read_only"
  io.github.jschuller/servicenow-tables: "sys_user_has_role sys_user_grmember sys_group_has_role sys_user sys_user_group"
---

# Analyzing ServiceNow Access

Two jobs: review role and group hygiene across users, and explain why a call was denied or came back incomplete. Everything here is read-only. See `references/access-errors.md` for the denial messages and what each one means, and `references/acl-evaluation.md` for how ServiceNow decides access.

## Tables and roles

| Table | What it answers | Readable with |
|-------|-----------------|---------------|
| `sys_user_has_role` | Which user holds which role, directly or inherited | `itil` (all users' rows); `snc_read_only` alone gets 403 |
| `sys_user_grmember` | Group membership | `itil` |
| `sys_group_has_role` | Which roles a group grants | `itil` |
| `sys_user` | `active`, `last_login_time` | `snc_read_only` |
| `sys_security_acl` | The ACL rules themselves | `admin` / `security_admin` only: 403 for least-privilege identities |

Role names come through dot-walks (`role.name`). The role table itself (`sys_user_role`) usually hides its rows from least-privilege identities.

## When access is denied

- **403** on a table: not assessable with this identity. Say so, name the table, and move on; don't guess.
- **0 rows** or **fields missing from every row** (`list_records` adds a `warning`): possibly hidden by an ACL, not proof that nothing exists.
- **401 under API-key auth** on aggregates or single-record reads: a REST API access policy doesn't cover that API; table reads still work.

## Workflows

### 1. Who holds privileged roles

**Progress checklist:**
```
- [ ] List active admin and security_admin grants
- [ ] Flag inactive users and stale logins among them
- [ ] Separate direct grants from group grants
- [ ] Report counts and the accounts to review
```

1. List the grants, with enough user context to judge each one:
   ```
   list_records(table_name="sys_user_has_role", query="role.nameINadmin,security_admin^state=active", fields="user.user_name,user.active,user.last_login_time,role.name,inherited", limit=200)
   ```
2. A row with `inherited=false` is a direct grant. An inherited row came through a group or through a role that contains this one. To find the group, intersect the user's groups with the groups that grant the role (workflow 2, step 3):
   ```
   list_records(table_name="sys_user_grmember", query="user.user_name=<user>", fields="group.name", limit=100)
   ```
   `granted_by` still names the group on some instances, but ServiceNow has deprecated it, so don't rely on it.
3. Report the holder count per role, then the accounts to review first: inactive users, users with no recent login, and direct grants.

### 2. Roles granted outside groups

ServiceNow recommends granting roles through groups, so that moving a person between teams moves their access.

1. List direct grants on active users:
   ```
   list_records(table_name="sys_user_has_role", query="inherited=false^state=active^user.active=true", fields="user.user_name,role.name", limit=500)
   ```
2. Group the rows by role and by user. Many direct grants of the same role suggest a missing group.
3. Check which groups already grant that role:
   ```
   list_records(table_name="sys_group_has_role", query="role.name=<role>", fields="group.name,role.name,inherits", limit=50)
   ```

### 3. Roles left on inactive or long-absent users

1. Roles on deactivated users:
   ```
   list_records(table_name="sys_user_has_role", query="user.active=false^state=active", fields="user.user_name,role.name,inherited", limit=500)
   ```
2. Active users who have not logged in for 90 days, and active users who have never logged in:
   ```
   list_records(table_name="sys_user", query="active=true^last_login_timeRELATIVELT@dayofweek@ago@90", fields="user_name,last_login_time", limit=500)
   list_records(table_name="sys_user", query="active=true^last_login_timeISEMPTY", fields="user_name", limit=500)
   ```
3. Cross-check the users from step 2 against their roles (workflow 1, filtered by `user.user_name`). Integration and service accounts may never log in interactively, so confirm what an account is before calling it stale.

### 4. Explain a denial or an incomplete answer

**Progress checklist:**
```
- [ ] Capture the exact status and message
- [ ] Classify it with references/access-errors.md
- [ ] Check the caller's own roles
- [ ] Say what is and isn't assessable, and the next step
```

1. Take the status code and the message text exactly as returned; the message names the mechanism.
2. Classify it with `references/access-errors.md`.
3. Check the caller's roles with `get_current_user()`. It lists direct grants; inherited roles come through groups.
4. For "why can't user X see record Y": read X's roles and groups (workflow 1 filtered to that user), then explain from the role side using `references/acl-evaluation.md`. The ACL rules themselves need `admin`. Without them, say the rule-level answer is not assessable with this identity, and point an admin to ServiceNow's Access Analyzer, or to the Access Analysis agent where it is licensed.

## Tips

- A page can hold fewer rows than `limit` even when more readable records exist: the Table API applies the limit before ACLs remove rows. Keep paging with `offset` until a page comes back empty.
- Role changes take effect at the user's next session, so a fresh grant may not show in that user's current denials.
- Compare counts before trusting a filter. A condition on a field the identity can't read, or an operator ServiceNow doesn't recognise, is ignored rather than rejected, so the "filtered" result equals the unfiltered one.
- `aggregate_records` can count rows that `list_records` won't return. A count above the rows you can list means row-level ACLs are hiding records.
- Request every field you filter on in `fields=`: if it is hidden, `list_records` warns that it is missing from every row.
- Never read ACL `script` or `condition` bodies, or any field that can hold credentials, even with an admin identity. Names and counts answer hygiene questions.
- Treat the review as read-only. Recommend role removals; don't make them.
