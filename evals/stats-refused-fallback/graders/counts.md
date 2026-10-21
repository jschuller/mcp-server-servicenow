---
type: llm
---

The active incidents are 10: priority 1 has 1, priority 2 has 2, priority 3 has 3, priority 4 has 4.
PASS if the reply gives those four counts (labels such as "Critical" for 1 are fine) and does not present them as coming from an aggregate or statistics call that succeeded.
FAIL if it gives no counts, gives other counts, or stops because the aggregate call was refused.
