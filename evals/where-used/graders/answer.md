---
type: llm
---

The where-used data lists two business rules (Assignment group changes, Notify on reassignment), one client script (Clear assignee when group changes), one UI policy action (Make assigned to read-only when closed) and one script include (AssignmentUtils, a text match). ACLs could not be checked (403).
PASS if the reply names at least four of those five items and says the ACLs were not assessable with this identity.
FAIL if it claims there are no ACLs, invents items, or says it read or quoted script bodies.
