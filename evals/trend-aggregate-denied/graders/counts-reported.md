---
type: llm
---

The incident data has 12 rows: categories network 4, software 4, hardware 3, inquiry 1; vpn-cluster-a appears 3 times.
PASS if the reply gives counts by category consistent with that data, names vpn-cluster-a as a repeat CI, and does not present the counts as coming from an aggregate/statistics call that succeeded.
FAIL if it reports no counts, invents categories, or gives up because aggregates were refused.
