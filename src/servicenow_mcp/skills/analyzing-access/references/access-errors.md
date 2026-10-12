# Access denials and incomplete answers

How to read what ServiceNow sends back when an identity can't see something. The 403 and 401 messages below are quoted exactly, because they are what you match on. The first two 403s and the first 401 were observed on a Brazil instance through the Table and Aggregate APIs; the "API level" 403 is as documented.

## Denials

| Status | `message` / `detail` | What happened | What to say and do |
|--------|------------------------|---------------|--------------------|
| 403 | `User Not Authorized` / `User is unauthorized to access table: <table>` | A table-level read ACL refused the identity. Every field on the table is denied. | Not assessable with this identity. Name the table and the role usually needed. Don't retry with other filters. |
| 403 | `Insufficient rights to query records` / `Field(s) present in the query do not have permission to be read` | The query filters on fields the identity can't read, and the instance rejects such queries (the field-ACL check on inbound queries is on). | Drop the condition on the hidden field, or filter on a readable one. If the field matters, it needs a role that can read it. |
| 403 | `User Not Authorized` / `Failed API level ACL Validation` | An ACL on the REST API itself (not the table) refused the call. Seen on scripted and product APIs. | Not assessable through that API with this identity. |
| 401 | `User is not authenticated` / `Required to provide Auth information` | Under API-key auth: no REST API access policy maps the key's authentication profile to this API. Table reads can work while the Aggregate API or single-record GET is refused. | Not a bad key. Use `list_records` instead, or ask an admin to add an access policy for that API. |
| 401 | anything else | Wrong or expired credentials, or basic auth refused for this user. | Run `mcp-server-servicenow --check`; it names the cause. |

## Silent effects (no error at all)

| Symptom | Likely cause | How to check |
|---------|--------------|--------------|
| 0 rows, but the data should exist | Row-level read ACLs or security data filters hide every row. | `aggregate_records` may still count the rows. Count above zero with no rows listed means the rows are hidden. |
| Fewer rows than `limit`, yet more exist | The limit is applied before ACLs remove rows. | Keep paging with `offset`. |
| A requested field is missing from every row | A field-level ACL hides it, or the field doesn't exist. `list_records` adds a `warning` naming it. | Check the field on the table's schema, if the identity can read it. |
| A filter changes nothing: the "filtered" count equals the unfiltered count | A condition on a hidden field, or an operator the instance doesn't recognise, is ignored rather than rejected. Observed: `caused_byISEMPTY` and `caused_byISNOTEMPTY` returned the same 67 incidents. | Run the query without the condition and compare. Request the field in `fields=`; if it is hidden, the warning appears. |
| Counts are available but rows are not | The Aggregate API counted rows that the Table API won't return to this identity (observed: a count of 67 incidents next to 0 readable rows). | Report the count, and say the rows are not readable with this identity. |

## Sources
- [Enforce field ACLs for inbound query requests](https://www.servicenow.com/docs/r/brazil/platform-security/instance-security-hardening-settings/sc-enforce-field-acls-for-inbound-query-requests.html) · [source](https://github.com/ServiceNow/ServiceNowDocs/blob/753a7f0e8fac/markdown/platform-security/instance-security-hardening-settings/sc-enforce-field-acls-for-inbound-query-requests.md)
- [Configure API key - Token-based authentication](https://www.servicenow.com/docs/r/brazil/platform-security/authentication/configure-api-key.html) · [source](https://github.com/ServiceNow/ServiceNowDocs/blob/753a7f0e8fac/markdown/platform-security/authentication/configure-api-key.md)
- [Create REST API access policy](https://www.servicenow.com/docs/r/brazil/platform-security/authentication/create-api-access-policy.html) · [source](https://github.com/ServiceNow/ServiceNowDocs/blob/753a7f0e8fac/markdown/platform-security/authentication/create-api-access-policy.md)
- [Table API](https://www.servicenow.com/docs/r/brazil/api-reference/rest-apis/c_TableAPI.html) · [source](https://github.com/ServiceNow/ServiceNowDocs/blob/753a7f0e8fac/markdown/api-reference/rest-apis/c_TableAPI.md)
- [Security data filters](https://www.servicenow.com/docs/r/brazil/platform-security/security-data-filters.html) · [source](https://github.com/ServiceNow/ServiceNowDocs/blob/753a7f0e8fac/markdown/platform-security/security-data-filters.md)
