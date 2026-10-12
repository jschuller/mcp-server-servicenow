# How ServiceNow decides access

A summary, in our own words, of how access control lists (ACLs) are evaluated. Use it to explain an outcome from the role side when the ACL records themselves are not readable. Reading `sys_security_acl` needs `admin` or `security_admin`.

## One rule passes only when every part passes

An ACL rule has up to four parts: required roles, a data condition, security attributes, and a script. The rule passes only if all of its parts pass. A part left empty counts as passing. A rule that is empty or broken denies.

## Deny-Unless first, then Allow-If

- **Deny-Unless** rules are checked first. Every matching Deny-Unless rule must pass, or access is denied. Passing them does not grant access on its own.
- **Allow-If** rules come next. Among the rules that match at the same level, passing any one is enough.
- If nothing matches at all, access is allowed. In practice the base system's wildcard rules almost always match something.

## Table first, then field

For a record, both the table rule and the field rule must pass.

- **Table rules** are looked up from the most specific match to the least specific: the table itself, then its parent tables, then the wildcard `*`. Failing at table level denies every field on the table.
- **Field rules** are looked up in six steps:
  1. `table.field`
  2. `parent.field`
  3. `*.field`
  4. `table.*`
  5. `parent.*`
  6. `*.*`

  The search stops at the first level with a matching rule.

## Before and after the query

- Before a query runs, only the role requirements of field rules are checked.
- After it runs, conditions and scripts are checked record by record. Rows that fail are dropped, and fields that fail lose their value. Through the Table API the field disappears from the row.
- **Security data filters** work differently: they are added to the query itself, so restricted rows never leave the database and no "rows hidden" notice appears.

## Roles

- A user holds the roles granted to them directly, the roles of every group they belong to, and every role those roles contain.
- ServiceNow recommends granting roles through groups built around a persona.
- `security_admin` is an elevated role. It must be switched on for the session before ACLs can be edited, and only an `admin` can grant `admin`.

## When the rule-level answer is needed

An admin can use **Access Analyzer**, a Store app that needs the `access_analyzer_admin` role. It evaluates one user's access to a record, and compares two users or two sets of rules.

On Brazil instances with Now Assist (ServiceNow Otto), the **Access Analysis** agent answers the same question in the assistant panel:
- It needs `access_analyzer_admin` or `user_admin`.
- It reports Passed, Blocked or Undefined, and names the deciding rule, role or condition.
- It runs with the caller's own permissions.

Both tools run on the instance, so this server only points to them.

## Sources
- [Explore Access Control Lists](https://www.servicenow.com/docs/r/brazil/platform-security/access-control/exploring-access-control-list.html) · [source](https://github.com/ServiceNow/ServiceNowDocs/blob/753a7f0e8fac/markdown/platform-security/access-control/exploring-access-control-list.md)
- [ACL types](https://www.servicenow.com/docs/r/brazil/platform-security/access-control/acl-rule-types.html) · [source](https://github.com/ServiceNow/ServiceNowDocs/blob/753a7f0e8fac/markdown/platform-security/access-control/acl-rule-types.md)
- [Deny-Unless ACL](https://www.servicenow.com/docs/r/brazil/platform-security/access-control/acl-denial-behavior.html) · [source](https://github.com/ServiceNow/ServiceNowDocs/blob/753a7f0e8fac/markdown/platform-security/access-control/acl-denial-behavior.md)
- [Security data filters](https://www.servicenow.com/docs/r/brazil/platform-security/security-data-filters.html) · [source](https://github.com/ServiceNow/ServiceNowDocs/blob/753a7f0e8fac/markdown/platform-security/security-data-filters.md)
- [Prevent duplicate entries with Contextual Security: Role Management V2](https://www.servicenow.com/docs/r/brazil/platform-security/access-control/Role-Mgmt-V2.html) · [source](https://github.com/ServiceNow/ServiceNowDocs/blob/753a7f0e8fac/markdown/platform-security/access-control/Role-Mgmt-V2.md)
- [Elevated privilege roles](https://www.servicenow.com/docs/r/brazil/platform-security/c_ElevatedPrivilege.html) · [source](https://github.com/ServiceNow/ServiceNowDocs/blob/753a7f0e8fac/markdown/platform-security/c_ElevatedPrivilege.md)
- [Assign a role to a user](https://www.servicenow.com/docs/r/brazil/platform-administration/user-administration/t_AssignARoleToAUser.html) · [source](https://github.com/ServiceNow/ServiceNowDocs/blob/753a7f0e8fac/markdown/platform-administration/user-administration/t_AssignARoleToAUser.md)
- [Using Access Analyzer](https://www.servicenow.com/docs/r/brazil/platform-security/use-access-analyzer.html) · [source](https://github.com/ServiceNow/ServiceNowDocs/blob/753a7f0e8fac/markdown/platform-security/use-access-analyzer.md)
- [Access Analysis AI Agent](https://www.servicenow.com/docs/r/brazil/intelligent-experiences/access-analysis-agent.html) · [source](https://github.com/ServiceNow/ServiceNowDocs/blob/753a7f0e8fac/markdown/intelligent-experiences/access-analysis-agent.md)
