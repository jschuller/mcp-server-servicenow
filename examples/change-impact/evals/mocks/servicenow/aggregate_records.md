---
error: true
---

Authentication failed (401). Check the API key and that a REST API access policy maps it for this API and method (GET). Table reads may still work with this key: count with list_records (the same query, fields="sys_id", limit=1000, paging with offset) instead of aggregate_records. URL: https://example.service-now.com/api/now/stats/{{input.table_name}} | Response: {"error":{"message":"User is not authenticated","detail":"Required to provide Auth information"},"status":"failure"}
