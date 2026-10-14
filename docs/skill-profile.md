# The ServiceNow skill profile

What a skill written for mcp-server-servicenow looks like, what the validator checks, and why it works this way. The guide for authors is [EXTENDING.md](../EXTENDING.md). This page is the precise reference.

## A skill is a plain Agent Skill

A skill is a folder holding a `SKILL.md` file, in the [Agent Skills](https://agentskills.io/specification) format that Claude Code, Claude, Codex, VS Code with Copilot, Cursor, opencode, Gemini CLI, pi and many other clients load natively. Nothing about it is specific to this server except the profile below. A skill that follows it still installs anywhere.

This server ships four such skills inside the package (`src/servicenow_mcp/skills/`) and serves them over MCP as `skill://<name>/SKILL.md` (SEP-2640). Skills you write live in your own repository and install in your client like any other skill.

## The profile

### Frontmatter

| Field | Rule |
|-------|------|
| `name` | Required. 1-64 lowercase letters, digits and single hyphens; equal to the folder name |
| `description` | Required, at most 1,024 characters: what the skill does, then the words a user would type when they need it |
| `license` | Recommended; a warning when missing |
| `metadata.io.github.jschuller/servicenow-roles` | The roles the skill needs, space-separated, e.g. `"itil snc_read_only"` |
| `metadata.io.github.jschuller/servicenow-tables` | Every table the skill's tool calls read, space-separated. Required as soon as the skill calls a tool with a table |
| `metadata.io.github.jschuller/servicenow-writes` | The write tools the skill calls, space-separated, e.g. `"create_record"`. Leave it out for a read-only skill |

The metadata keys carry a reverse-domain prefix, because the Agent Skills specification asks for "reasonably unique" keys, and SEP-2640 uses the same convention. Values are strings, because the specification defines `metadata` as string-to-string.

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
  - a 403 means "not assessable with this identity". Name the role it needs; more access means another identity configured in the server, never credentials asked for in the conversation;
  - 0 rows or fields missing from every row mean "possibly hidden by an ACL";
  - under API-key auth, a 401 from the Aggregate API or a single-record read means a REST API access policy doesn't cover it.
- **Sources**: cite ServiceNow's documentation by link, in your own words. Pair the readable page with the ServiceNowDocs file at the commit you read:

  ```
  - [Page title](https://www.servicenow.com/docs/r/brazil/<area>/<page>.html) · [source](https://github.com/ServiceNow/ServiceNowDocs/blob/<commit>/markdown/<area>/<page>.md)
  ```

## The validator

`mcp-server-servicenow --validate-skills PATH [PATH ...] [--strict]` runs offline. A path is a skill folder or any folder above skills: every `SKILL.md` below it is checked, including hidden folders such as `.claude/skills` (installers read them) but not `.git`, virtual environments or `node_modules`, unless such a folder holds a `SKILL.md` itself (Claude Code loads `skills/node_modules/SKILL.md` as a skill). It prints one line per skill with a `sha256:` digest of its files, then each finding, then a result line. The exit code is 1 on any error, and with `--strict` on any warning too.

| Errors | Warnings |
|--------|----------|
| Frontmatter missing, not YAML, or breaking the name/description rules | No `license` |
| Frontmatter that runs code or pre-approves tools: `hooks`, `allowed-tools`, `shell` | `context`, `agent` or `background`, which run the skill elsewhere; a field that is neither Agent Skills nor Claude Code |
| Frontmatter that Claude Code could read with other keys than this check: see [Frontmatter layout](#frontmatter-layout) | |
| `SKILL.md`, `.claude-plugin/plugin.json`, `marketplace.json` or a location Claude Code loads as code, spelled in another letter case (`skill.md`, `Hooks/`): on macOS and Windows Claude Code opens them all the same | |
| `` !`command` `` after a line start or whitespace, or ```` ```! ```` anywhere in the text: Claude Code runs it when the skill loads | |
| A file that isn't `.md`/`.txt`/`.csv`, a hidden file or folder, a symlink, not UTF-8; a symlinked folder anywhere in the path | A call to a write tool that `servicenow-writes` doesn't declare, in code or prose |
| More than 512 files or 16 MiB | A link outside servicenow.com/docs and ServiceNowDocs |
| A relative link that leaves the skill or points nowhere | Text that looks like a credential or token |
| A tool call with an invalid table, field list or `order_by`, or a refused `javascript:` | A declared table the skill never mentions |
| A tool call reading a table that isn't declared | A code block that names a tool but doesn't parse |
| Invalid names in the metadata keys, or a `servicenow-writes` entry that isn't a write tool | A function that isn't a tool of this server |
| | A skill name that is also one of this server's skills |
| | A declared write tool that no call uses |

### Frontmatter layout

Claude Code reads frontmatter with its own parser: it ends the block at the first `---`, even inside a value, parses it as YAML 1.2, and when that fails it quotes `key: value` lines and parses again. This check reads YAML 1.1. Frontmatter those readers could disagree on could hide `hooks`, `allowed-tools` or `shell` from the check, so the validator accepts only a layout that fixes the keys in the text itself:

- the first line is `---` alone (trailing spaces allowed), and the block ends at the next such line;
- no `---` anywhere inside the block (write a dash or two);
- no tabs, no control characters (a lone carriage return included), no U+2028/U+2029 line or paragraph separators, no byte-order mark and no bidi controls (CRLF line endings are fine);
- each line in column 0 is a key written as a plain name starting with a letter or `_` (`name: value`), a `- item` or a `#` comment, and those keys are exactly the ones the YAML holds (so no quoted, `?`, `on:`/`yes:` or `__proto__` keys, and no duplicate keys);
- a value that goes on over several lines is indented on each of them;
- no anchors, aliases or tags (`&`, `*`, `!`), and no `\uD800`-`\uDFFF` escapes.

Ordinary frontmatter (folded `description: >-` blocks, a `metadata:` map, lists of paths) passes unchanged.

A skill that declares its writes passes `--strict`, and its line in the output names them (`writes: create_record`), so a reviewer sees them without reading the body. The skill should still say to ask before writing. This repository's own skills run with `--strict` in CI.

The digest covers every file's path and content, so you can pin a skill: if anything changes, the digest changes.

## The plugin wrapper

`claude plugin eval` tests only plugins, so a skills repository that wants evals carries a minimal Claude Code plugin manifest, `.claude-plugin/plugin.json`. The validator checks every folder that holds one:

| Errors | Warnings |
|--------|----------|
| Any key other than metadata (`name`, `displayName`, `version`, `description`, `author`, `homepage`, `repository`, `license`, `keywords`, `metadata`, `$schema`, and the directory listing's `documentationUrl`, `supportUrl`, `privacyPolicyUrl` and `termsOfServiceUrl`), `skills` and `mcpServers`: `hooks`, `agents`, `commands`, `workflows`, `userConfig`, `dependencies` and the rest add code or behaviour | A remote (`url`) server, which the validator can't confirm is this one |
| Locations Claude Code loads without a key: `hooks/`, `agents/`, `commands/`, `monitors/`, `output-styles/`, `workflows/`, `themes/`, `bin/`, `.mcp.json`, `.lsp.json`, `settings.json`; a `package.json` (installed when the plugin loads); `uv.toml` or `[tool.uv]` settings (they can change which package `uvx` runs) | `--allow-js-queries`, or `SERVICENOW_ALLOW_JS_QUERIES` set to anything but false |
| `mcpServers` with anything other than one server: `command` `uvx`, `args` starting with `mcp-server-servicenow[==version]` followed only by `--read-only`, `--debug` or `--allow-js-queries`, and no keys besides `command`, `args`, `env` | `SERVICENOW_AUDIT_LOG` naming a file on the evaluator's machine |
| An `env` key that isn't one of this server's `SERVICENOW_*` settings (no `PYTHONPATH`, no `UV_*`) | `evals/mocks/<server>/_tools.json` that differs from this server's tools: names, descriptions, schemas or hints |
| A password, client secret or API key, or the instance or token URL, that isn't `${NAME}` or `${NAME:-}` with the setting's own name (no literal, no default, no other variable): a repository mustn't choose where the user's credentials go | A `tool_used` grader that names no skill of this plugin, or tools of another plugin or server name |
| A `skills` path outside the plugin folder, a symlink, or one that holds a symlink. Skills a `skills` path declares are checked wherever they are, `node_modules` included | |
| A `.claude-plugin/marketplace.json` with keys other than `name`, `owner`, `description`, `version`, `metadata`, `plugins`, `$schema`; a `metadata.pluginRoot`; an entry with keys other than metadata, `source`, `category` and `tags` (no `strict`, no components); or a `source` that isn't a folder in the repository holding `.claude-plugin/plugin.json`. Plugins it lists are checked wherever they are | |
| Eval case, grader or mock frontmatter that doesn't parse: `claude plugin eval` skips the file | |

The reason is that `claude plugin eval` runs a plugin's hooks, agents and servers on the evaluator's machine, as the evaluator, and the skills' users run what the skills carry. A repository that passes with `--strict` declares nothing that runs except this server, and its skills are instructions only. The validator is a static check, not a sandbox: read what you run, and run unfamiliar suites in a container or CI runner. Pin the server (`mcp-server-servicenow==0.9.1`) in the wrapper and in the Action.

## The eval kit

- **`mcp-server-servicenow --eval-mocks PLUGIN_DIR`** writes `evals/mocks/<server>/` for the wrapper's server:
  - `_tools.json`: this version's `tools/list` response, with the version in `_meta`. It is rewritten on every run.
  - Default mocks modelled on the start-here identity (`itil` + `snc_read_only` over an API key):
    - `list_records` answers from `fixtures/<table>.json`;
    - `aggregate_records` is refused with the server's 401 text;
    - `get_table_schema` is refused with its 403 text;
    - `get_current_user` returns a read-only user.
  - An empty fixture, `{"count": 0, "records": []}`, for every table the skills declare.

  Existing mocks and fixtures are kept. Tools without a mock, including every write tool, aren't available in a run.
- **`mcp-server-servicenow --eval-baseline PLUGIN_DIR OUT_DIR`** copies the plugin without its skills: the same name, server, cases and mocks. Running the cases against it measures the bare tools. `OUT_DIR` must be outside the plugin; a later run replaces a folder an earlier run wrote, and refuses any other folder that isn't empty. Symlinks in `evals/` are refused.
- **`mcp-server-servicenow --eval-summary RESULT_JSON [--baseline RESULT_JSON] [--badge FILE]`** reads a finished `aggregate-result.json` (`schemaVersion` 1) and prints a Markdown summary. It records:
  - cases passed and the suite score;
  - Δ vs tools only, per case and overall, from the baseline run. Graders that check a skill fired are left out, since they can't pass without skills;
  - Δ vs no plugin, as the eval tool reports it;
  - the model and judge;
  - runs per case and the Claude Code version;
  - the server version that generated the mocks;
  - the list-price cost, the start time and the commit;
  - the kind of result, "CI-run" (with the GitHub Actions run URL) or "self-reported";
  - a per-case table and a command to reproduce the run.

  It never prints the run's local paths. It refuses a partial run, a run where some runs ended in an error (a usage limit scores 0 without marking the run partial), and a baseline made with another model or judge. Cases missing from the baseline are named, and the commit is marked when the skills or evals had uncommitted edits. `--badge` writes a [shields.io endpoint](https://shields.io/badges/endpoint-badge) JSON file.

## The citation check

`actions/validate-skills/check_citations.py PATH [...]` finds every `github.com/ServiceNow/ServiceNowDocs/blob/<commit>/<path>` link and checks it against a blobless clone of ServiceNowDocs (about two seconds). The release branch comes from the `servicenow.com/docs/r/<release>/` link on the same line, and defaults to `brazil`.

- **Error:** the commit or the path at that commit doesn't exist.
- **Error:** the page is gone from the head of its release branch. It moved or was removed, so re-cite it.
- **Warning:** the page changed since the cited commit. Re-read it, and re-cite it if your text still holds.

It never checks servicenow.com by HTTP, because the docs site answers 200 for pages that don't exist.

## The GitHub Action

`jschuller/mcp-server-servicenow/actions/validate-skills` runs both checks in your own repository. Pin it to a full commit SHA, with its release in a comment, as GitHub recommends for third-party actions: a tag can be moved, a commit can't. The Action runs the validator from `server-version` and its own citation check, so its pinned release can trail the server's; the citation check follows the pin.

```yaml
- uses: jschuller/mcp-server-servicenow/actions/validate-skills@66ba9254971e36dad67d3c0f609d9161d29d0d1c # v0.9.0
  with:
    path: .                 # space-separated folders; . also checks the plugin wrapper
    server-version: "0.9.1" # pin it; empty means the latest release
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

**AD-6, 2026-10-12: the server's skills cover the Now Platform; application skills and their eval results live with their authors.**

- **Context.**
  - ServiceNow ships its own ITSM, CMDB and other MCP servers.
  - Its documentation files CMDB and CSDM, users, groups and roles, ACLs, dictionary and choice lists, and update sets under the platform, and incident, problem and change under IT Service Management.
  - The owner wants community skills kept separate from the server, tailored to each organisation, with evals they can share.
- **Decision.**
  - `triaging-incidents` moves to `examples/incident-triage`.
  - `servicenow-cmdb` keeps the data model, health, data quality and CSDM, which ServiceNow's CMDB server doesn't cover.
  - The unreleased 0.8.1 ships inside 0.9.0, because removing a skill is a breaking change.
  - We add the plugin-wrapper check, `--eval-mocks` and `--eval-summary`, and a template repository with validation and eval workflows.
  - Eval results live in the author's repository: `RESULTS.md` plus the committed mocks, at a tag, in the style of Hugging Face's `.eval_results`.
  - Discovery is the GitHub topic `servicenow-mcp-skill` and Discussions › Skills.
- **Rejected:**
  - a results index or leaderboard in this repository (hosting, review load, implied endorsement);
  - verifying anyone's results.

## Open questions

- **Prompts and the Skills extension.** Prompts move to 0.10. The server will declare `io.modelcontextprotocol/skills` once FastMCP implements `skills/list` (FastMCP issue #5016).
- **Behaviour evals in CI.** The template's `evals.yml` runs an author's suite with the author's own credential. Running this repository's suites in its CI would need a credential and a usage budget, which has not been decided.
- **Δ against the bare tools** is measured by a second run against a tools-only copy (`--eval-baseline`). A built-in third arm in `claude plugin eval` would make it one command.
- **Tables declared but used through dot-walks.** The validator only flags a declared table the skill never mentions. A finer rule would need to parse dot-walks.
