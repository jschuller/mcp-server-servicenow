---
name: my-servicenow-skill
description: "One or two sentences: what this skill does, then the words a user would type when they need it. Use when the user asks about <topic>, <synonym>, or '<a typical question>'."
license: MIT
metadata:
  author: your-name
  version: "0.1.0"
  io.github.jschuller/servicenow-roles: "itil snc_read_only"
  io.github.jschuller/servicenow-tables: "incident"
---

# My ServiceNow Skill

One paragraph: the job this skill does, for whom, and what it never does (for example "read-only: it recommends changes and makes none").

## Tables and roles

| Table | What it gives | Readable with |
|-------|---------------|---------------|
| `incident` | What you read from it | The least role that can read it |

Declare every table your tool calls read in `io.github.jschuller/servicenow-tables`, and the roles in `io.github.jschuller/servicenow-roles`. If the skill calls a write tool, add `io.github.jschuller/servicenow-writes` with its name. Test the skill on a developer instance with an identity that holds exactly those roles.

## When access is denied

- **403** on a table: not assessable with this identity. Say which table and which role it needs. More access means another identity configured in the server; never ask for credentials in the conversation.
- **0 rows** or **fields missing** from every row (`list_records` adds a `warning`): possibly hidden by an ACL. Don't report "nothing found" as a fact.
- **`aggregate_records` refused** (401 under API-key auth): count from `list_records` rows instead.

## Workflow

**Progress checklist:**
```
- [ ] Step one
- [ ] Step two
- [ ] Report, separating facts from recommendations
```

1. Write each tool call in a code block, as a call, so the validator can check it:
   ```
   list_records(table_name="incident", query="active=true^priority<=2", fields="number,short_description,priority,active", limit=20)
   ```
2. Put long reference material in `references/` and link to it: see [the notes](references/notes.md).
3. Say what the report contains.

## Tips

- `list_records` and `list_ci` check the fields you filter on in `query=` as well as those in `fields=`: if one is hidden or misspelled, the warning names it. A dot-walk in `query=` is checked whole only when you pass `fields=`.
- Write in your own words, and cite ServiceNow's documentation by link (see `references/notes.md`).
