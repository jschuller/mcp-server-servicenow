# The ServiceNow skill profile

What a skill written for mcp-server-servicenow looks like, what the validator checks, and why it works this way. The guide for authors is [EXTENDING.md](../EXTENDING.md). This page is the precise reference.

## A skill is a plain Agent Skill

A skill is a folder holding a `SKILL.md` file, in the [Agent Skills](https://agentskills.io/specification) format that Claude Code, Claude, Codex, VS Code with Copilot, Cursor, opencode, Gemini CLI, pi and many other clients load natively. Nothing about it is specific to this server except the profile below. A skill that follows it still installs anywhere.

This server ships five such skills inside the package (`src/servicenow_mcp/skills/`) and serves them over MCP as `skill://<name>/SKILL.md` (SEP-2640). Skills you write live in your own repository and install in your client like any other skill.

## The profile

### Frontmatter

| Field | Rule |
|-------|------|
| `name` | Required. 1-64 lowercase letters, digits and single hyphens; equal to the folder name |
| `description` | Required, at most 1,024 characters: what the skill does, then the words a user would type when they need it |
| `license` | Recommended; a warning when missing |
| `metadata.io.github.jschuller/servicenow-roles` | The roles the skill needs, space-separated, e.g. `"itil snc_read_only"` |
| `metadata.io.github.jschuller/servicenow-tables` | Every table the skill's tool calls read, space-separated. Required as soon as the skill calls a tool with a table |

The two metadata keys carry a reverse-domain prefix, because the Agent Skills specification asks for "reasonably unique" keys, and SEP-2640 uses the same convention. Values are strings, because the specification defines `metadata` as string-to-string.

### Tool calls

Write every tool call in a fenced code block, as a call:

```
list_records(table_name="task_sla", query="has_breached=true", fields="sla,sla.name,stage", limit=500)
```

The validator parses these blocks. Each call must name a tool this server has, use valid table, field and `order_by` names, and use no `javascript:` beyond the date helpers the server accepts. Any table it reads must be declared in the metadata.

Placeholders such as `<ci_sys_id>` or `table_name="<table_name>"` are allowed; the parts that are placeholders are not checked.

Calls in inline code (single backticks) are not checked. Use them for asides.

### Files

- Only `.md`, `.txt` and `.csv` files: no scripts, no binaries, no JSON or YAML.
- No hidden files and no symlinks.
- At most 512 files and 16 MiB per skill (SEP-2640's limits).
- Relative links stay inside the skill folder and point at files that exist.

These rules keep a skill safe to read and to serve: it is instructions and reference text, nothing that runs.

### Content

- A **Tables and roles** section: each table, what it gives, and the least role that reads it.
- A **When access is denied** section:
  - a 403 means "not assessable with this identity";
  - 0 rows or fields missing from every row mean "possibly hidden by an ACL";
  - under API-key auth, a 401 from the Aggregate API or a single-record read means a REST API access policy doesn't cover it.
- **Sources**: cite ServiceNow's documentation by link, in your own words. Pair the readable page with the ServiceNowDocs file at the commit you read:

  ```
  - [Page title](https://www.servicenow.com/docs/r/brazil/<area>/<page>.html) · [source](https://github.com/ServiceNow/ServiceNowDocs/blob/<commit>/markdown/<area>/<page>.md)
  ```

## The validator

`mcp-server-servicenow --validate-skills PATH [PATH ...] [--strict]` runs offline. A path is a skill folder or any folder above skills: every `SKILL.md` below it is checked, skipping hidden folders. It prints one line per skill with a `sha256:` digest of its files, then each finding, then a result line. The exit code is 1 on any error, and with `--strict` on any warning too.

| Errors | Warnings |
|--------|----------|
| Frontmatter missing, not YAML, or breaking the name/description rules | No `license` |
| A file that isn't `.md`/`.txt`/`.csv`, a hidden file or folder, a symlink, not UTF-8 | A call to a write tool (say so in the skill, and ask before writing) |
| More than 512 files or 16 MiB | A link outside servicenow.com/docs and ServiceNowDocs |
| A relative link that leaves the skill or points nowhere | Text that looks like a credential or token |
| A tool call with an invalid table, field list or `order_by`, or a refused `javascript:` | A declared table the skill never mentions |
| A tool call reading a table that isn't declared | A code block that names a tool but doesn't parse |
| Invalid names in the metadata keys | A function that isn't a tool of this server |
| | A skill name that is also one of this server's skills |

The digest covers every file's path and content, so you can pin a skill: if anything changes, the digest changes.

## The citation check

`actions/validate-skills/check_citations.py PATH [...]` finds every `github.com/ServiceNow/ServiceNowDocs/blob/<commit>/<path>` link and checks it against a blobless clone of ServiceNowDocs (about two seconds). The release branch comes from the `servicenow.com/docs/r/<release>/` link on the same line, and defaults to `brazil`.

- **Error:** the commit or the path at that commit doesn't exist.
- **Error:** the page is gone from the head of its release branch. It moved or was removed, so re-cite it.
- **Warning:** the page changed since the cited commit. Re-read it, and re-cite it if your text still holds.

It never checks servicenow.com by HTTP, because the docs site answers 200 for pages that don't exist.

## The GitHub Action

`jschuller/mcp-server-servicenow/actions/validate-skills@<tag>` runs both checks in your own repository:

```yaml
- uses: jschuller/mcp-server-servicenow/actions/validate-skills@v0.9.0
  with:
    path: skills            # space-separated folders
    server-version: "0.9.0" # pin it; empty means the latest release
    strict: "true"
    citations: "true"
```

The action needs a release of mcp-server-servicenow that has `--validate-skills`, which is 0.9.0 or later.

## Decision record

**AD-5, 2026-10-11: user content is plain Agent Skills, with no pack format; loading it through the server is deferred.**

- **Context.** We planned "content packs": a folder with a `pack.json`, loaded by the server with `--packs` and served as `skill://<pack>/<skill>/SKILL.md`.
- **The packs duplicated what exists.** A pack's unit of content was already an Agent Skill, and its manifest repeated fields that skill frontmatter already has (name, description, licence, version).
- **Clients already load skills.** Every client this server is tested with loads skill folders natively.
- **Local is the better home for an organisation's own know-how.** SEP-2640 treats MCP-served skills as untrusted input.
- **Decision.** There is no pack format, and "skills" is the only name. What this project adds on top of the open standard:
  - two metadata keys;
  - the validator;
  - the citation check and the Action;
  - a template and an example;
  - the guide.
- **This server's own skills are not converted.** Namespacing them would change `skill://<name>/…`, and they are versioned with the tools they teach. They are the reference implementation of the profile and pass the validator in CI.
- **Deferred: loading skills through the server.** The design is `--skills DIR` / `SERVICENOW_SKILLS`:
  - each folder becomes `add_provider(SkillsDirectoryProvider(DIR, supporting_files="resources"), namespace=<folder name>)` on FastMCP 4.1, served as `skill://<folder>/<skill>/SKILL.md`;
  - it is off by default;
  - startup refuses a duplicate name, a name this server already uses, or a folder that fails validation, because FastMCP otherwise keeps the first duplicate silently;
  - it logs each folder's digest and adds one line to the server instructions;
  - it never adds tools, code or permissions.

  The only case it would serve is a shared HTTP deployment pushing an organisation's skills to every client. Build it when someone asks for that in Discussions.
- **Rejected:**
  - a curated library of community packs in this repository (hosting and licence liability, review load);
  - Python entry points or code extensions;
  - fetching skills from git or a registry at startup;
  - a check DSL or a `run_check` tool;
  - signing, dependencies, hot reload.

## Open questions

- **Prompts and the Skills extension.** Prompts move to 0.10. The server will declare `io.modelcontextprotocol/skills` once FastMCP implements `skills/list` (FastMCP issue #5016).
- **Behaviour evals in CI.** The examples carry `claude plugin eval` cases with mocked tools. Running them in this repository's CI would need a credential and a usage budget, which has not been decided.
- **Tables declared but used through dot-walks.** The validator only flags a declared table the skill never mentions. A finer rule would need to parse dot-walks.
