---
name: exploring-tables
description: "Exploring any ServiceNow table — schema, field types, sample records, relationships, and data patterns. Use when the user mentions tables, schemas, fields, data dictionary, sys_dictionary, sys_db_object, table structure, \"what fields does X have,\" or wants to understand a ServiceNow table they haven't worked with before."
allowed-tools: "mcp__servicenow__get_table_schema, mcp__servicenow__list_records, mcp__servicenow__get_record, mcp__servicenow__list_ci"
metadata:
  author: jschuller
  version: "1.0.0"
  mcp-server: mcp-server-servicenow
---

# Exploring ServiceNow Tables

General-purpose table exploration — schema discovery, data profiling, and table comparison.

## Workflows

### 1. Explore a Table

Get the full picture of any ServiceNow table.

**Progress checklist** (copy into your response):
```
- [ ] Get table schema
- [ ] Pull sample records
- [ ] Summarize field types, mandatory fields, reference fields
```

1. Get the table schema (field definitions, types, mandatory flags):
   ```
   get_table_schema(table_name="<table_name>")
   ```
2. Pull sample records to see real data:
   ```
   list_records(table_name="<table_name>", limit=5)
   ```
3. Summarize:
   - Total field count and types (string, integer, reference, boolean, etc.)
   - Mandatory fields (the ones users must populate)
   - Reference fields (links to other tables — these define relationships)
   - Choice fields (fields with dropdown values)

### 2. Compare Tables

Side-by-side schema comparison between two related tables.

**Progress checklist:**
```
- [ ] Get schema for table A
- [ ] Get schema for table B
- [ ] Compare field overlap and differences
```

1. Get schemas for both tables:
   ```
   get_table_schema(table_name="<table_a>")
   get_table_schema(table_name="<table_b>")
   ```
2. Compare:
   - Fields present in both (shared/inherited from a common parent)
   - Fields unique to each table
   - Differences in field types or mandatory flags
   - Reference field targets

### 3. Find Tables

Discover tables matching a keyword by querying `sys_db_object`.

**Progress checklist:**
```
- [ ] Query sys_db_object for matching tables
- [ ] Get record counts for top matches
- [ ] Summarize results
```

1. Search for tables by name or label:
   ```
   list_records(table_name="sys_db_object", query="nameLIKE<keyword>", fields="name,label,super_class,sys_id", limit=20)
   ```
2. For top matches, get a sample record to confirm the table has data:
   ```
   list_records(table_name="<matched_table>", limit=1)
   ```
3. Summarize: table name, label, parent class, whether it has data.

### 4. Data Profiling

Sample records and assess data quality for a table.

**Progress checklist:**
```
- [ ] Get table schema
- [ ] Pull sample records
- [ ] Check null rates on key fields
- [ ] Identify unused or sparse columns
```

1. Get the schema to know what fields exist:
   ```
   get_table_schema(table_name="<table_name>")
   ```
2. Pull a larger sample:
   ```
   list_records(table_name="<table_name>", limit=20)
   ```
3. For key fields, check how many have empty values:
   ```
   list_records(table_name="<table_name>", query="<field_name>ISEMPTY", limit=1, fields="sys_id")
   ```
4. Report:
   - Fields with high null rates (potential data quality issues)
   - Fields that appear unused (always empty or default)
   - Reference fields that point to empty/missing records
   - Recommendations for data cleanup

## Tips

- Use `fields` parameter to limit returned data: `fields="sys_id,name,state"`.
- The `sys_db_object` table contains all table definitions. Use it to discover tables by keyword.
- The `sys_dictionary` table contains field-level metadata. Query it for advanced schema details: `list_records(table_name="sys_dictionary", query="name=<table_name>")`.
- Encoded query cheat sheet: `=` (equals), `LIKE` (contains), `ISEMPTY` (null), `^` (AND), `^OR` (OR).
