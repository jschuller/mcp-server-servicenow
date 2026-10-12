---
type: llm
---

The data: "Priority 1 resolution (1 hour)" and "P1 resolution - legacy" have the same start condition (overlap); "Priority 3 resolution (1 day)" has no task SLA rows (never attaches); "Network group resolution" (an OLA) breached 2 of 2.
PASS if the reply identifies the two overlapping P1 definitions and at least one of: the never-attaching P3 definition, or the Network OLA's breach rate.
FAIL if it misses the P1 overlap or invents definitions.
