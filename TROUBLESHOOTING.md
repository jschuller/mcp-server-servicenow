# Troubleshooting

## Reading Error Messages

Error messages from this MCP server include diagnostic context from ServiceNow's response — the response body and key headers (`X-Is-Logged-In`, `X-Transaction-ID`). This context often pinpoints the exact cause:

- **403 with `WebServicePolicyValidator`** → The table needs `ws_access=true` in its dictionary entry
- **403 with ACL reference** → The user lacks the required role or ACL for that operation
- **404 with table name** → The table doesn't exist or is misspelled
- **401 with `X-Is-Logged-In: false`** → Credentials are invalid (not just expired)

The `X-Transaction-ID` header can be given to a ServiceNow admin to look up the exact server-side log entry.

## Instance is hibernating
PDIs hibernate after inactivity. Wake it at [developer.servicenow.com](https://developer.servicenow.com) — click your instance and select "Wake Up". You'll get HTML login pages instead of JSON until it's awake.

## 401 Unauthorized
- **OAuth proxy: browser login succeeds but every MCP call returns `invalid_token`:** the SN OAuth app's Scope Restriction is "Securely scoped" (the Zurich+ default), which blocks Table API access. Set it to "Broadly scoped" in the Application Registry record, or add REST API Access Policies covering the Table/Stats APIs
- **Basic auth rejected with `"Required to provide Auth information"` even though the password is correct:** the instance enforces ServiceNow's basic-auth restriction (`glide.authenticate.basic_auth.restriction.enforce`, default on new PDIs since mid-2026). Grant the integration user the `snc_basic_auth_api_access` role — or use the OAuth 2.1 MCP endpoint auth, which is unaffected
- **Basic auth:** Verify username/password are correct; check that the user has the `rest_api_explorer` or `admin` role
- **OAuth:** Ensure the OAuth Application Registry entry is active and the redirect URI matches. Try regenerating the client secret
- **Expired token:** OAuth tokens expire; the server retries once automatically, but if both attempts fail, check your credentials

## 403 Access Denied
The error message includes the ServiceNow response body, which typically names the specific policy or ACL that blocked access. Common causes:
- **`WebServicePolicyValidator`** — The table's `ws_access` property is not set to `true`. Fix: go to System Definition > Tables, find the table, check "Allow access to this table via web services"
- **Missing role** — The integration user needs the appropriate role (e.g., `itil` for incident, `cmdb_read` for CMDB). Check the error body for the specific role required
- **Cross-scope restriction** — If accessing a scoped app's table, ensure cross-scope privileges are configured

## OAuth `get_current_user` returns different fields
With OAuth bearer tokens, `get_current_user` uses a Table API fallback (the UI endpoint requires session auth). The response fields are the same but sourced from `sys_user` instead of the UI API.
