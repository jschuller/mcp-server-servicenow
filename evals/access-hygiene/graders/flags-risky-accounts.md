---
type: llm
---

The fixture data has these risky privileged accounts: ops.contractor (inactive but still holds admin), svc.legacy-sync (admin, never logged in), jdoe.admin (admin granted directly, last login in March 2026).
PASS if the reply names at least two of those three accounts as risks and gives the reason for each.
FAIL if it names none of them, invents accounts not in the data, or claims it changed or removed any role.
