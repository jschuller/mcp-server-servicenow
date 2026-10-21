# Changelog

## [Unreleased]

Read-only developer-loop tools (where-used, record history, structured output), readable
values (`display_value`) and checked filters, and the fixes from an independent review of
the repository.

### Upgrade notes
- **Eight read tools now publish an `outputSchema`**: `list_records`, `list_ci`,
  `get_ci_relationships`, `get_system_properties`, `list_update_sets`,
  `list_update_set_changes`, `get_table_schema` and the new `find_references`. The
  JSON text block is unchanged. A client that validates results gets typed data; with the
  FastMCP client, `result.data` becomes a typed object, so read `result.structured_content`
  for the plain dict.
- **Static tokens: an entry with a `:` is now `name:token`.** If one of your tokens
  contains `:` and the part before it looks like a name (up to 32 letters, digits, `.`, `_`,
  `-`), only the part after it is accepted: replace that token (`openssl rand -hex 32` never
  contains `:`). A repeated token or name, or a name with nothing after the `:`, now stops
  startup. Tokens under 32 characters, and an HTTP listener without `--read-only`, only
  log a warning.
- **Regenerate your eval mocks** (`--eval-mocks`): `_tools.json` now carries the output
  schemas, `find_references` and `display_value`, and the validator compares them.
- **`list_records` and `list_ci` check the fields in `query=`.** When `fields=` is given,
  they add the fields the query filters on to the request and remove them from the rows
  again, so you still get exactly the fields you asked for, but the request differs: a
  test that asserts the exact `sysparm_fields` of a filtered call needs the query's
  fields appended.

### Added
- **`display_value`** on `list_records`, `get_record`, `list_ci`, `get_ci` and
  `aggregate_records`: `"true"` returns labels in place of sys_ids and choice values, and
  `"all"` returns `{display_value, value}` per field, so the sys_id stays beside the name.
  The default, `"false"`, sends nothing new. `query=` still filters on stored values.
- **A warning for conditions the instance ignored.** The Table API silently drops a
  condition on a field that doesn't exist, and, depending on the field's ACL, on a field an
  ACL hides (some answer 403), so the "filtered" result is unfiltered. `list_records` and
  `list_ci` now check the fields named in `query=`, not only those in `fields=`, and they
  count the terms that name no column, even when no row comes back: a label like
  `NameLIKEa` (columns are lowercase), or a name with an invisible or non-ASCII character. A
  dot-walk in `query=` is checked whole only when `fields=` is given; without it, only the
  reference field is. A missing dot-walk is reported more cautiously: it is also missing when
  only the referenced records are unreadable, and then the condition applied. Terms inside
  RLQUERY and SUBQUERY blocks, catalog variables and tags are not checked, nor are more than
  50 query fields. Terms that name no column are counted, never quoted, and field names are
  echoed in field-name characters only, at most 60 each, since query text can come from a
  record. `list_ci` results carry the same `warning`.
- **CMDB data-quality checks** in the servicenow-cmdb skill (2.1.0, workflow 4): each check is
  a count over a total, with a sample. Unhandled duplicates (`duplicate_of` on active CIs, as
  the CMDB Data Foundations dashboard counts them, and open de-duplication tasks) and the same name within a class
  (`group_by=name`, `having=count^name^>^1`); stale CIs by `sys_updated_on` and by
  `last_discovered`, with never-discovered CIs counted separately; CIs with no relationship
  through `RLQUERYcmdb_rel_ci` (one block per query); broken relationships; missing key
  fields per class; locations with no parent, models with no owner, and assets with no CI.
  `dl_definition` is gone from the skill: it holds Data Lookup definitions, not quality rules.
- **Joins through dot-walks** in the analyzing-access skill (2.1.0, workflow 5): team
  rosters, role holders with their groups, and distinct people holding a role
  (`group_by=user`), with why a plain count gives grants rather than people.
- **`find_references`**: where-used for a table or one field. It lists business rules,
  client scripts, UI policies (or their field actions), ACLs, script includes and
  reference fields, by name and sys_id only, never script or ACL bodies. Script matches
  are text matches, and only the exact table is matched (run it again for a parent
  table). A source the identity can't read (403, or a 401 from an access policy that leaves
  its table out) is reported in `not_assessable`, and the others still answer. Under basic
  auth the first 401 is an error, and so is a refused OAuth secret or a timeout, raised at the first source so a bad
  password costs one failed login. The exploring-tables skill drives it (workflow 7).
- **Record history** in the exploring-tables skill (2.1.0, workflow 6): a record's work notes and
  comments (`sys_journal_field`) and field changes (`sys_audit`) as one timeline. Without
  `audit_viewer` the journal returns 0 rows rather than a 403, and the skill reports that
  as not assessable.
- **`response_format`** on `list_records` and `list_ci`: `concise` returns reference
  fields as bare sys_ids, without instance URLs. The default, `detailed`, is unchanged.
- **Structured output that survives the size limit**: a list over 500 KB keeps its
  shape, holding the rows that fit, with `truncated: true` and `next_offset`; when not
  even one row fits, the list is empty and a `note` says to ask for fewer fields. Other
  tools are cut to text as before. The audit log flags both.
- **An API key's 401 names the read that still works**: on the Stats API, count with
  `list_records`; on a single-record read, `list_records` with `sys_id=`. With the old
  wording the eval's tools-only agent never fell back (0 of 5 runs); with the new one it
  did in 4.5 of 5.
- **Named static tokens**: `MCP_STATIC_TOKENS` entries may be `name:token`, and the name
  is what the audit log records as `user`, so attribution survives reordering.
- The skill validator warns on a mock `expect` for a parameter with a default (such a
  call aborts the case), and on an `expect` the tool doesn't take.
- Eval cases: record-history, stats-refused-fallback, where-used.
- [docs/privacy.md](docs/privacy.md): the server talks only to your instance and sends no
  telemetry; what the audit log keeps.

### Changed
- `get_table_schema` adds a `note` when the parent tables can't be read (`sys_db_object`
  unavailable): the hierarchy may be incomplete and inherited fields are missing.
- **The template's workflows ask for least privilege** (`permissions: {}`), keep checkout
  credentials out of the workspace and pin their tools; the template adds a Dependabot
  config with a 7-day cooldown and a zizmor workflow that audits its Actions.
- The `javascript:` refusal names the two-step alternative: query the other table first,
  then pass its sys_ids with `IN`.
- The `having` description of `aggregate_records` gives the Aggregate API's form,
  `aggregate^field^operator^value` (`count^name^>^1`), not `COUNT>5`.
- **The Claude Code plugin pins its server** to the same release
  (`uvx mcp-server-servicenow==0.9.2`), as Anthropic's plugin directory requires. Plugin
  users get a new server when the plugin updates, so the skills and the server always
  come from the same release. CI checks the pin with the other version fields, and
  RELEASING.md now publishes to PyPI before main (the marketplace) moves.
- One description in pyproject, the plugin and the marketplace; server.json carries a short
  form of it.
- The plugin manifest carries the directory listing fields (`displayName`,
  `documentationUrl`, `supportUrl`, `privacyPolicyUrl`), and the skill validator accepts
  them, plus `termsOfServiceUrl`, in a skills wrapper.
- **Renovate auto-merges GitHub Actions updates only**, after a 7-day release age, and
  never this repository's own Action; Python dependency bumps are reviewed PRs.
- The plugin passes `SERVICENOW_TOKEN_URL` and `SERVICENOW_DEBUG`; `server.json` lists
  `SERVICENOW_DEBUG`.
- The server turns off FastMCP's startup check for a newer FastMCP on PyPI, so it makes no
  request except to your instance.
- Tests count tools from one list (`tests/inventory.py`), and CONTRIBUTING lists the steps
  of adding a tool.

### Fixed
- **The audit log names static-token callers.** Behind MultiAuth (every static-token
  deployment) the audit `user` had been FastMCP's internal verifier list, not the token's
  name.
- Deployment docs: the from-source HTTP example shows the token it generates, Docker
  passes secrets from the environment, Cloud Run uses Secret Manager, and the Cloud Run
  check sends the Google identity token in `X-Serverless-Authorization`.
- The audit log is described as it is: written values are never logged, and encoded
  queries are logged with secret-like values masked, so they can hold filter values.
- SECURITY.md supports 0.9.x.
- The configuration examples no longer show literal passwords.

## [0.9.1] - 2026-10-13

A security fix for the skill validator, plus the small fixes the 0.9.0 review deferred.

### Upgrade notes
- **The validator accepts a narrower frontmatter layout** (see Security). A skill that
  passed 0.9.0 can now fail if its frontmatter holds a tab, a `---` inside a value, a
  value that goes on in column 0, a quoted, duplicate or `yes:`/`on:` key, a control or
  bidi character, or a YAML anchor or tag. Ordinary
  frontmatter, such as folded `description: >-` blocks, a `metadata:` map or lists of
  paths, is unaffected, and all the skills in this repository pass unchanged.
- **The template pins the validate-skills Action by commit SHA** (`@66ba925… # v0.9.0`)
  instead of `@v0.9.0`; the Action itself is unchanged. Do the same in your own
  workflows: a tag can be moved.

### Security
- **Skill frontmatter that Claude Code could read with other keys than the validator is
  refused.** Claude Code ends the frontmatter at the first `---` (even inside a value),
  parses it with Bun's YAML 1.2 parser and, when that fails, quotes `key: value` lines
  and parses again. The validator reads YAML 1.1 with PyYAML. A `hooks`,
  `allowed-tools` or `shell` line that PyYAML took as part of a multi-line value could
  therefore reach Claude Code unchecked; 0.9.0 passed such frontmatter. The validator
  now accepts only a layout that fixes the top-level keys in the text itself:
  - `---` fences alone on their lines, and no `---` inside the block;
  - no tabs, control characters, line separators, byte-order mark or bidi controls;
  - every column-0 line a plain key, a list item or a comment, and those keys exactly
    the ones the YAML holds;
  - continuation lines indented, and no anchors, aliases or tags.

  This was checked against a port of Claude Code 2.1.296's frontmatter reader running
  on Bun 1.4.3, the version Claude Code embeds, over about 239,000 generated
  frontmatters. In about 27,700 of them a code key was hidden from PyYAML, and all of
  those are refused. None of the frontmatters the validator accepts gives Claude Code
  a different set of keys. See [Frontmatter layout](docs/skill-profile.md#frontmatter-layout).
- **A `skill.md` (any letter case but `SKILL.md`) is checked as the skill it is.** Claude
  Code opens `SKILL.md` by name, so on a case-insensitive disk (macOS, Windows) it loads
  `skill.md`; the validator, matching the exact name, skipped the folder, so its
  frontmatter could carry `hooks` past the check and the digest. The same held for
  `.claude-plugin/plugin.json`, `marketplace.json` and the locations Claude Code loads
  as code (`Hooks/`, `Settings.json`). All are now found in any letter case, the way
  macOS and Windows compare names, and any other spelling is an error, even beside the
  exact one (git can hold both, and either may win a checkout on macOS). Present since
  0.9.0.
- **Identifier patterns end in `\Z`, not `$`.** `$` also matches before a final
  newline, so the server's own guard let `"incident\n"` through as a table name into the
  URL path. The same applied to `order_by`, an update-set state, a role name, a schema
  URI and the end of an allowed date helper in a query. In the validator and the eval
  kit, `"mcp-server-servicenow\n"` passed as the package and `"false\n"` as a safe
  setting, and so did a trailing newline in a skill name, a role or the plugin's server
  name.

### Fixed
- `--eval-summary` refuses a tools-only baseline with a different number of runs per
  case, as it already did for other models. A 1-run baseline was accepted against a
  3-run result, and the printed baseline command then said `--runs 3`.
- `--eval-summary` reports a result file with malformed fields (`"suite": "x"`) in
  one line that names the field, instead of a traceback.
- `skills: "/etc"` in a plugin manifest is reported as outside the plugin, not as a
  symlink (macOS makes `/etc` a symlink). A skills path the file system can't read is an
  error, not a traceback.
- Frontmatter PyYAML can't read at all (a `\U00110000` escape, deep nesting) is an
  error for that skill instead of a crash of the whole run. YAML errors are one line,
  with the file's line number; duplicate and YAML 1.1 boolean keys are named as such;
  and frontmatter that fails these checks no longer also reports undeclared tables,
  writes or a missing licence.
- `--eval-summary` reports a malformed model, root or case or grader name in one line,
  compares runs case by case, and says when a baseline has no per-run grader results.
- The examples' `RESULTS.md` files use the current summary format. The runs and
  numbers are unchanged; the update adds the Score note, `--threshold`, and a pinned
  baseline command.

## [0.9.0] - 2026-10-13

"A platform core, and your own skills." The skills shipped in the package now cover
only the Now Platform: tables and schema, access, update sets, and CMDB data quality.
Application skills such as incident triage live outside the package. ServiceNow ships
its own ITSM and CMDB MCP servers, and an organisation's own skills belong in its own
repository. This release adds what an author needs to write, check and test such
skills: a validator, a GitHub Action, a template and examples. It also includes the
content and fixes prepared as 0.8.1, which was never released.

### Upgrade notes
- **`skill://triaging-incidents` is gone from the server.** It is now
  [`examples/incident-triage`](examples/incident-triage/). Install it like any skill:
  `npx skills add jschuller/mcp-server-servicenow --skill triaging-incidents`, or copy
  the folder into your client's skills directory. The tools are unchanged; any table,
  incident included, still works.
- **`--check` probes `sys_user_group` instead of `incident`**: a base-platform table
  that both `itil` and `snc_read_only` identities can read. An identity without ITSM
  roles no longer shows a misleading table warning.
- **`servicenow-cmdb` names `cmdb_read` and `sn_cmdb_user` as its roles,** taken from
  the instance's read ACLs. `itil` still works, since it holds both.
- **`servicenow-cmdb` no longer handles dependency maps or "what depends on X".** Its
  description dropped those triggers, and it points CI search and change impact to
  ServiceNow's CMDB MCP server. `get_ci_relationships` still works.
- **The server instructions no longer send incident questions to a skill.** They list
  only the four platform skills; install the incident-triage example to get that
  workflow back.
- **The skill validator is stricter** (see Security). A skills repository that passed
  in a pre-release build may now fail: for example, `uvx` options before the package,
  `env` keys other than `SERVICENOW_*`, or unknown manifest keys.

### Security
- **Skills and skills repositories are checked for code that would run as the user.**
  The validator refuses:
  - skill frontmatter that registers hooks, pre-approves tools or picks a shell
    (`hooks`, `allowed-tools`, `shell`), and `` !`command` `` and ```` ```! ````
    shell injection, matched the way Claude Code matches it;
  - plugin manifest keys other than metadata, `skills` and `mcpServers`, and the
    locations Claude Code loads as code (`hooks/`, `bin/`, `workflows/` and the rest),
    a `package.json`, and uv settings;
  - a `marketplace.json` entry that carries components (`strict: false`, `hooks` and
    the rest) or a source other than a plugin folder in the repository;
  - a server entry that isn't `uvx mcp-server-servicenow[==version]` first, with only
    `--read-only`, `--debug` or `--allow-js-queries` after it; `env` keys other than
    this server's settings (no `PYTHONPATH` or `UV_*`); credentials, the instance URL
    or the token URL with a literal value, a default or another variable's name, so a
    repository can't send the user's credentials to a host it chooses;
  - symlinked folders anywhere it searches. It now searches hidden folders such as
    `.claude/skills` too, because installers read them, and checks every skill a
    plugin's `skills` paths or a marketplace declare, even in `node_modules` or
    `.venv`, and skill folders with those names.

  A pre-release review found each of these could pass `--strict` while running other
  code for whoever evaluated or installed the skills.
- **The eval kit stays inside the plugin.** `--eval-mocks` refuses table and server
  names that would write elsewhere, and `--eval-baseline` refuses an output folder
  inside the plugin and symlinks in `evals/`.
- **The `javascript:` guard accepts the list UI's date ranges.** The `@` that separates
  the two ends of an `ON`, `NOTON` or `BETWEEN` range is now allowed after a date helper.
  So is `gs.dateGenerate()` with a literal date and `'start'`, `'end'` or a literal time,
  e.g. `opened_atON2026-10-01@javascript:gs.dateGenerate('2026-10-01','start')@...`.
  - Every `javascript:` occurrence is still checked on its own.
  - Anything other than a date helper is refused, including a non-literal
    `dateGenerate` argument.
  - This widens what the guard accepts, so it is listed here.

### Added
- **`--validate-skills PATH [...]`** (with **`--strict`**) checks skill folders offline
  against the Agent Skills specification and this server's profile:
  - frontmatter;
  - declared roles, tables and write tools (`io.github.jschuller/servicenow-roles`,
    `-tables`, `-writes`);
  - tool calls in code blocks, checked against the server's identifier and
    `javascript:` rules;
  - text-only files with no symlinks, within SEP-2640's size limits;
  - links that stay inside the skill.

  It warns on undeclared write-tool calls, outside links and credential-like text, and
  prints a `sha256:` digest per skill for pinning, plus the write tools it declares.
- **The validator checks plugin wrappers.** A folder with `.claude-plugin/plugin.json`
  may declare only metadata, skills and one server that runs
  `uvx mcp-server-servicenow`, with this server's own settings (see Security).
  `claude plugin eval` runs a plugin's code as the evaluator, and a repository that
  passes with `--strict` carries none. It also warns when a saved `_tools.json` no
  longer matches the server's tools (names, descriptions, schemas or hints), and when
  a grader names a skill, plugin or server that isn't there.
- **`--eval-mocks PLUGIN_DIR`** writes mocks for `claude plugin eval`:
  - this version's tool list;
  - default mocks modelled on a least-privilege identity, using the server's own 401
    and 403 texts;
  - an empty fixture for every declared table.

  It keeps your edits.
- **`--eval-baseline PLUGIN_DIR OUT_DIR`** copies a skills plugin without its skills,
  so the same cases measure the bare tools.
- **`--eval-summary RESULT_JSON [--baseline RESULT_JSON] [--badge FILE]`** turns a
  finished run into a `RESULTS.md` table: score, what the skills add over the bare
  tools per case, Δ vs no plugin, models, versions, commit, "CI-run" or
  "self-reported", and a command to reproduce it. `--badge` writes a shields.io badge.
  It refuses a partial run, a run where some runs ended in an error (a usage limit
  scores 0), and a baseline made with other models. It marks a commit with uncommitted
  edits to the skills or evals.
  - **Why the baseline:** on the examples, Δ vs no plugin was +1.00 on every case that
    reads data, but the bare tools alone already scored 1.00 on change collision, so
    the skill added nothing there. They scored 0.00 on the trend case, where the skill's
    row-count fallback adds +1.00.
- **Eval case files are checked:** frontmatter that doesn't parse is an error, because
  `claude plugin eval` skips the case. The example `sla-overlap` case had an unquoted
  colon and had never run.
- **`actions/validate-skills`**, a composite GitHub Action that runs the validator and a
  ServiceNowDocs citation check (blobless clone: an error when a cited page disappears,
  a warning when it changed). This repository's CI runs it with `--strict` on the
  shipped skills and the examples.
- **`examples/`:**
  - `template/`: the content of the template repository, with a validation workflow,
    a hand-started eval workflow that writes `RESULTS.md`, a pinned plugin wrapper and an
    eval case;
  - `incident-triage/`: the former core skill, with its eval cases;
  - `change-impact/`: two original example skills, `assessing-change-impact` and
    `reviewing-sla-definitions`, with mocked eval cases.
- **`skill://analyzing-access`**:
  - who holds `admin` and `security_admin`;
  - roles granted outside groups or left on inactive and long-absent users;
  - what each 401 and 403 message, empty result and missing field means.
  It reads `sys_user_has_role`, `sys_user_grmember`, `sys_group_has_role` and `sys_user`
  (`itil` + `snc_read_only` is enough). It explains ACL outcomes from the role side and
  points admins to Access Analyzer and the Access Analysis agent. References:
  `access-errors.md`, `acl-evaluation.md`.
- **`servicenow-cmdb`:** CSDM 5 conformance by stage, read from `sn_getwell_csdm_score`
  (`references/csdm5.md`).
- **`exploring-tables`:**
  - choice lists;
  - a sampling fallback when the schema returns 403;
  - the encoded-query reference (below).
- **`reviewing-update-sets`:** preview problems and collisions of retrieved update sets,
  read-only. Previewing writes, so the skill never runs one.
- **Frontmatter metadata:** every skill declares its roles and tables.
- **`list_records` warning:** when `fields=` names a field that is missing from every
  returned row, the result carries a `warning`. The field either doesn't exist or an ACL
  hides it, and conditions on such a field are ignored rather than rejected. Live:
  `caused_byISEMPTY` and `caused_byISNOTEMPTY` returned the same incidents.
- **`evals/`:** a trial `claude plugin eval` suite that runs against mocked tools, so it
  needs no instance and no credentials.
- **Docs:** `EXTENDING.md` (the guide), `docs/skill-profile.md` (the reference and the
  decision record), and a Discussions "Skills" form.
- **Dependency:** `pyyaml` is now a direct dependency (it was transitive through FastMCP).

### Changed
- **`servicenow-cmdb` is about the CMDB as a data model:** class hierarchy, raw
  relationships, health, data quality and CSDM conformance. It points CI search and
  change impact to ServiceNow's CMDB MCP server.
- **The encoded-query reference moved.** It now lives at
  `skill://exploring-tables/references/query-syntax.md`, so clients that install the
  skills natively get it too. `servicenow://help/query-syntax` stays as an alias for the
  same file. The reference was rewritten and checked against a live instance:
  - added: the RELATIVE family, `ON`/`NOTON`/`BETWEEN` ranges, field-to-field comparisons,
    the conditions an instance ignores instead of rejecting, and platform-table patterns;
  - removed: the `MORETHAN`, `LESSTHAN` and `DATEPART` rows, which did not filter as
    described.
- **Server instructions** list the four platform skills. They ask the model to name
  filtered fields in `fields=`, and to read a 403 as "not assessable".
  - The skill line now says to read the skill "before your first tool call on a task
    below" (it was "before multi-step ITSM or CMDB work").
  - In fresh Claude Code sessions (2.1.296, Sonnet), the old wording plus the new text
    read the skill first in 1 of 8 runs of "what's on fire", against 5 of 7 for 0.8.0.
  - The new wording read it in 7 of 7. On an access question it read it in 5 of 5,
    against 1 of 4 before. It still skipped the skill for "which user am I?" (3 of 3).
    Those runs still listed `triaging-incidents`.
  - With the four platform skills, a fresh-session test read the matching skill before
    its first data call in 28 of 28 runs (7 per skill).
- **On a 403, the instructions add that more access means another identity configured
  in the server, never credentials asked for in the chat.**
  - Before: in a fresh-session test, 1 of 7 update-set answers offered to continue if the
    user supplied "an admin token".
  - After: none of 5 did. `reviewing-update-sets`, the template and the skill profile
    say the same.
- **Tool parameter examples lead with platform tables.** The descriptions, plugin and
  package keywords no longer present the server as an ITSM tool.

### Removed
- **`triaging-incidents` from the package** (see Upgrade notes).

## [0.8.0] - 2026-10-11

"One server, spec-native surface." The four ServiceNow skills stop being a
Claude-Code-plugin-only artifact and become part of the MCP contract: they ship
in the wheel and are served over MCP as `skill://` resources in the SEP-2640
URI shape (the Skills extension went Final on 2026-09-11). Every `pip`/`uvx`
install on every client gets the guided workflows. The server does not yet
declare the `io.modelcontextprotocol/skills` extension (`skills/list`), which
waits for FastMCP support. MCP prompts are deferred to 0.9.

The release also moves governance to where ServiceNow enforces it. The table
allow/deny lists are gone (they didn't stop dot-walks); write tools hide
themselves for an `snc_read_only` identity, so the start-here setup needs no
flag; OAuth client credentials open headless and CI use; and `--check`
diagnoses a connection in one command. `--read-only` stays as the server-side
guarantee.

Verified on 2026-10-10/11 against a Brazil instance with Claude Code 2.1.296,
VS Code 1.140 with GitHub Copilot, Codex CLI 0.162.1, opencode 1.19.0,
Antigravity CLI 1.1.20 and pi 1.1.0, and the write paths as an admin's own
OAuth token over Streamable HTTP — see "Verified clients" in
`docs/clients.md`.

### Upgrade notes
- **Breaking: `--write-confirm` / `SERVICENOW_WRITE_CONFIRM` are removed.** The
  server no longer starts with the flag; the environment variable is ignored.
  `update_record`, `update_ci` and `delete_record` lose their `confirm`
  argument. Approval of writes is the MCP client's job (tool annotations),
  with ServiceNow's ACLs and `snc_read_only` as the boundary.
- **Breaking: the table allow/deny lists are removed.** `--table-allowlist`
  and `--table-denylist` no longer exist (the server won't start with them),
  and `SERVICENOW_TABLE_ALLOWLIST` / `SERVICENOW_TABLE_DENYLIST` are ignored.
  They were a targeting guard, not a data boundary: with `sys_user*` denied, a
  live `incident` read with `fields=caller_id.email` still returned user data
  through the dot-walk. Scope tables and APIs on the instance instead, where
  ServiceNow enforces it for every client: ACLs and roles on the integration
  user, Machine Identity access controls and REST API access policies
  ([Security Best Practices Guide](https://www.servicenow.com/content/dam/servicenow-assets/public/en-us/doc-type/resource-center/white-paper/instance-security-best-practice.pdf),
  Australia, pp. 17 and 37). Identifier, field-list and `javascript:`
  validation stay.
- **The API-key header defaults to `x-sn-apikey`**, ServiceNow's default
  auth parameter (was `X-ServiceNow-API-Key`, which worked only where an
  admin had created a custom parameter by that name). If yours did, set
  `SERVICENOW_API_KEY_HEADER=X-ServiceNow-API-Key`.
- **Breaking (Claude Code plugin):** the four `/servicenow:*` slash commands
  are now the skills' own commands — `/servicenow:triage` →
  `/servicenow:triaging-incidents`, `/servicenow:cmdb` →
  `/servicenow:servicenow-cmdb`, `/servicenow:explore-table` →
  `/servicenow:exploring-tables`, `/servicenow:review-update-set` →
  `/servicenow:reviewing-update-sets`. The `servicenow-admin` subagent is
  removed (its audit, trend-report and batch-review patterns live in the
  skills). The skills no longer carry `allowed-tools`, so Claude Code may now
  ask before the MCP tools a skill uses.
- **`get_current_user` returns one shape for every auth type:** `user_name`,
  `user_display_name`, `user_email`, `user_sys_id`, `roles`, plus any extra
  `fields` you ask for. Basic-auth callers previously got the raw UI-endpoint
  payload. `roles` is now a list of role names, not a comma-separated string.
- **Eleven new resources** appear in `resources/list` (per skill: `SKILL.md`,
  `_manifest` with SHA-256 digests, `references/*.md`): 15 instead of 4.
- **The server sends `instructions`** naming the skill URIs (~200 tokens).
- **Audit:** an unknown resource URI is classified `unknown_resource` (was
  `unknown_tool`).
- **FastMCP floor is 4.1.0**; Python 3.14 is supported.

### Added
- **`mcp-server-servicenow --check`**: a read-only connection diagnostic with
  the same flags and environment as the server. One line per check — the
  configuration it understood, whether the instance answered (DNS, TLS, a
  hibernating PDI), the identity and its direct roles, whether write tools
  are hidden, a Table API read, schema access (a 403 names
  `personalize_dictionary`) and the Aggregate API (an API key without an
  access policy for it is reported as a policy limit, as is the per-record
  GET behind `get_record`). Exit code 0 when
  authentication and a read work. It never prints a secret, so the output
  can go straight into a Q&A post.
- **OAuth client credentials grant** for headless use (CI, scheduled jobs,
  SSO-only instances): with `SERVICENOW_AUTH_TYPE=oauth` and no username or
  password, the server requests a client-credentials token (client id and
  secret in the form body) and acts as the OAuth client's application user.
  A username and password together keep the password grant; setting only one
  is a startup error. The startup log names the grant, a refresh falls back to
  a new grant of the same type, and audit lines read
  `oauth-client:<client_id>`. Instance setup: configuration.md.
- **Write tools are hidden when the identity holds `snc_read_only`**, without
  any flag: ServiceNow would refuse those writes anyway, admin included. One
  lookup of the caller's own `sys_user_has_role` rows (5-second limit) for the
  configured account, or an `sn_read_only` claim per token behind the OAuth
  proxy. A call to a hidden tool is refused with a clear message and audited
  as `denied`. It fails open — if the lookup fails or times out the tools stay
  listed and ServiceNow refuses the write — so it is a convenience, not a
  security control; `--read-only` remains the server-side guarantee.
- Skills served over MCP via FastMCP's `SkillsDirectoryProvider`
  (`src/servicenow_mcp/skills/`, package data).
- Server `instructions`, and `render_instructions(namespace)` for servers that
  mount this one: FastMCP does not forward a mounted server's instructions and
  rewrites its URIs (`skill://snow/…`), so a parent can pass
  `render_instructions("snow")` on. `tests/test_mount.py` pins that policy and
  audit still apply through a parent.
- CI: Python 3.14, and a check that the wheel carries the 4 skills.

### Fixed
- The `servicenow-cmdb` skill named CMDB Health tables that don't exist
  (`cmdb_health_audit`, `cmdb_health_rule`, `cmdb_health_kpi`; the instance
  answers 400). It now reads `cmdb_health_scorecard`, `cmdb_health_result`,
  `cmdb_health_metric` and the staleness and orphan rule tables, each checked
  live with a least-privilege identity, and falls back to the full audit when
  the CMDB Health jobs have not run.
- `servicenow://cmdb/classes` stopped silently at 200 rows; a base instance
  has 700+ `cmdb_ci*` classes. It now pages through them (up to 5,000) and
  says `truncated: true` if it ever stops at that bound.
- The instance URL is normalised at startup: surrounding spaces, a trailing
  slash, a missing `https://`, a bare instance name (`dev12345` →
  `https://dev12345.service-now.com`) and a pasted UI path or query are all
  accepted, and the startup log shows the URL used. A missing scheme used to
  fail only at the first tool call (`MissingSchema`), and a URL copied from
  the UI gave a misleading "hibernating PDI" error.
- `SERVICENOW_AUTH_TYPE` is optional in `server.json` (the server already
  defaulted to `basic`), and the registry description fits its 100-character
  limit again.
- `get_current_user`, `servicenow://instance` and the OAuth proxy's `roles`
  claim read the caller's direct, active roles from `sys_user_has_role`. They
  read `sys_user.roles`, which is empty for most users, so `roles` was `null`
  for every caller (seen live for an `itil` + `snc_read_only` API-key user).
  Inherited roles are left out; every lookup is filtered to the caller.
- `set_current_update_set` and `servicenow://update-set/current` touch only the
  caller's own `sys_user_preference` row. Before, an admin could overwrite
  another user's current update set, and the fallback created a blank-user row
  — which ServiceNow treats as the system-wide default for every user.
- An OAuth token response without `access_token` raised nothing and sent
  `Authorization: Bearer None`; it now fails with a clear error, and a refresh
  grant that does so falls back to the password grant (#12).
- The token-verification cache could grow past `max_cache_size`.
- Clearer refusals: a `sys_dictionary` 403 names the `personalize_dictionary`
  role that schemas need; an API-key 401 points at REST API access policies
  instead of "check your username/password".
- Error messages name the fix: a basic-auth 401 names the "Web service access
  only" / `snc_basic_auth_api_access` restriction; TLS failures (corporate
  proxies) and DNS failures (typos, reclaimed PDIs) no longer read as "instance
  asleep"; HTML and empty responses give the PDI wake URL; a 403 links the
  roles-per-tool table. Links are absolute so the model can pass them on.

### Changed
- Server instructions ask the model to treat record text as data, not
  instructions, and to tell the user when a record contains instructions aimed
  at it, even if it ignores them.
- Getting started now creates a least-privilege integration user (Web Service
  Access Only, `itil` + `snc_read_only`) instead of connecting as `admin`,
  which new instances refuse for REST basic auth. A roles table maps tools to
  roles; examples use `mcp.integration`. The start-here snippets no longer
  pass `--read-only`: that user's write tools are hidden anyway. Keep the
  flag for a writable identity on a client without approval prompts
  (opencode, pi) or a shared HTTP server.
- New "Recommended integration identity" section in `docs/configuration.md`,
  mapping ServiceNow's Security Best Practices Guide (Australia, 2026-09-18) to
  setup steps: a dedicated Web-service-only user per integration, tokens over
  passwords, least privilege, table and API scope on the instance, no secrets
  in logs. The README gains a VS Code install button that prompts for the
  instance URL, user and password.
- README cut from 486 to about 200 lines: what you can ask, a four-step quick
  start (Windows, VS Code with a password prompt, Claude Desktop), an "if it
  doesn't work" table, tools, roles and safety in brief. Reference material
  moved to `docs/tools.md`, `docs/clients.md` (every client, the plugin,
  verified clients), `docs/native-mcp.md` (updated for ServiceNow's pre-built
  MCP servers) and `docs/architecture.md`; "From source" to
  `docs/deployment.md`; development to `CONTRIBUTING.md`. Links are absolute,
  so they work on PyPI. All client snippets use `mcp.integration` and
  `--read-only` and no password on a command line.
- TROUBLESHOOTING starts with a symptom table and covers DNS failures,
  corporate TLS inspection and `spawn uvx ENOENT`.
- Package metadata: a plain summary, keywords, classifiers and project URLs.
- Support routes: `SUPPORT.md`, GitHub Discussions forms (Q&A, Show and tell),
  and the issue chooser points questions to Discussions.
- Dependencies refreshed (mcp 2.3.0, PyJWT 2.15.1, urllib3 2.8.0, anyio
  4.15.1, httpx2 2.13.1), clearing the open Dependabot alerts except PyJWT #38,
  which has no fixed release yet.
- Live tests (`scripts/stdio_smoke.py`, `tests/integration/`) take credentials
  from the environment only; the smoke has a `readonly` profile that changes
  nothing and a `write` profile for writable instances.

### Removed
- `commands/` and `agents/servicenow-admin.md`.
- Opt-in write confirmation (`--write-confirm`, `confirm.py`, the `confirm`
  tool argument, the audit `confirm`/`round` fields and the
  `cancelled`/`confirmation_required` outcomes). Where clients could show it,
  it came after their own approval prompt; where they couldn't, the model
  could pass `confirm=true` itself. About 290 lines of source and 360 of tests
  and smoke checks.

## [0.7.0] - 2026-09-05

"Developer data plane, with guardrails." Closes the write-safety and
auditability gap identified in the Action Fabric gap analysis, fixes the
correctness bugs found during that diligence, and restates what this server is
for: the raw Table API / schema / aggregates / update-set loop that ServiceNow's
native MCP Server Console excludes by design.

### Upgrade notes
No default-path change breaks a documented client, but five behaviours differ
from 0.6.x:
- **`delete_record` returns a dict** (`{"deleted": true, "table", "sys_id"}`)
  instead of the sentence `"Record … deleted from …"`.
- **`get_table_schema` / `servicenow://schema/{table}` include inherited
  fields by default** — `incident` now shows its `task` columns. Output gains
  `hierarchy` and per-field `defined_in` (existing keys unchanged); `limit`
  defaults to 200 (max 1000). Pass `include_inherited=false` for the old
  direct-only behaviour. Expect 2–3× more fields and one extra ServiceNow call
  per parent table.
- **`javascript:` in caller-supplied queries is restricted** to GlideSystem date
  helpers (`gs.daysAgo*`, `gs.beginningOf*`, `gs.endOf*`, `gs.*AgoStart/End`,
  `gs.now*`). Everything the shipped skills and the query-syntax resource teach
  still works; `gs.getUserName()`, `GlideRecord`, `;` etc. are rejected with a
  message naming `--allow-js-queries` / `SERVICENOW_ALLOW_JS_QUERIES=true`.
- **A JSON audit line per call is written to stderr by default.** Claude Desktop
  shows it in `mcp-server-servicenow.log`; Claude Code only in debug logs.
  `--audit-log off` or `--audit-log /path/file.jsonl` to change.
- **`MCP_STATIC_TOKENS` now requires ServiceNow service-account credentials**
  (basic, api_key, or OAuth client credentials) and no longer forwards the
  static token to ServiceNow. In 0.6.x that mode 401'd on every call, so
  nothing that worked stops working — unless you had pasted a real ServiceNow
  bearer into `MCP_STATIC_TOKENS` as a workaround.
- `update_record`, `update_ci` and `delete_record` gain an inert
  `confirm: bool = false` argument (only consulted under `--write-confirm`).

### Added
- **Tool annotations** on all 19 tools (`readOnlyHint`, `destructiveHint`,
  `idempotentHint`, `openWorldHint`) so clients can apply their own permission
  policies; Claude Code shows them in `/mcp`.
- **`--read-only` / `SERVICENOW_READ_ONLY`** — hides the 7 write tools and, as
  defence in depth, refuses any non-GET request in `make_sn_request`.
- **Table allow/deny lists** (`--table-allowlist`, `--table-denylist`; exact or
  glob, deny wins) enforced by a `PolicyMiddleware` on `table_name`,
  `class_name`, the fixed-table tools and the schema resource.
- **Opt-in destructive-call confirmation** (`--write-confirm`): `update_record`,
  `update_ci`, `delete_record` show the record's current values and ask via
  MCP elicitation — `ctx.elicit()` on handshake-era connections (Claude Code,
  Cursor), the 2026-07-28 multi round-trip `InputRequiredResult` on modern
  ones. Decline is final; a synthetic cancel (Claude Desktop/Cowork) or a
  client without elicitation falls back to an explicit `confirm=true`.
- **JSON audit log** (`AuditMiddleware`): user, auth mode, transport, tool,
  table, sys_id, redacted query, data keys, tags, outcome, duration. Never
  stdout, never values.
- `get_table_schema(include_inherited=…)` and the schema resource walk
  `sys_db_object.super_class` (depth ≤ 10, per-table queries with a child-first
  budget, graceful fallback when `sys_db_object` is unreadable).
- `get_ci_relationships` gains `limit` (default 100, max 1000) and `offset`.
- CLI helpers treat empty and unexpanded `${VAR}` environment values as unset —
  the Claude Code plugin can now pass every option through with
  `${VAR:-default}` without crashing startup when a var is not set.
- `servicenow://cmdb/classes` returns `super_class` as the parent's name
  instead of a `{link, value}` reference.
- **`.claude-plugin/marketplace.json`** — the plugin is now actually
  installable: `claude plugin marketplace add jschuller/mcp-server-servicenow`
  then `claude plugin install servicenow@mcp-server-servicenow`. Deliberately
  carries no `version` field, so it does not become a sixth version string to
  keep in sync (marketplace entries validate against `plugin.json` only when
  they declare one).

### Security
- **Encoded-query hardening**: caller-supplied `query`/`having` reject
  arbitrary `javascript:`; table names, sys_ids, `relation_type`, `state`,
  `order_by` and field lists are validated; URL path segments are
  percent-encoded so `../` or `?sysparm_query=` in an identifier can no longer
  rewrite a request or bypass a denylist.
- Static MCP tokens are tagged `sn_auth: service-account` and never forwarded
  to ServiceNow as a bearer.
- **`mcp-publisher` is pinned and checksum-verified** in `publish-mcp.yml`
  (v1.8.1, SHA-256 from that release's `checksums.txt`). It previously came
  from `releases/latest` unverified while running in a job holding the OIDC
  token that authorizes publishing to the `io.github.jschuller/*` namespace —
  the one unpinned artifact in an otherwise SHA-pinned pipeline.

### Fixed
- HTTP + `MCP_STATIC_TOKENS` mode: the caller's MCP token was sent to
  ServiceNow as `Authorization: Bearer`, so every call failed 401 with a
  misleading "per-user OAuth token may be expired" message. The configured
  service account is now used (any credential type), and the startup error is
  explicit when it is missing.
- `.claude-plugin/plugin.json` had drifted to 0.6.0; CI's version check now
  covers it (five fields).
- `SECURITY.md` supported-versions table (was still 0.3.x); README skills path
  (`skills/`, shipped via the plugin).
- **README's plugin install command never existed.** It documented
  `claude plugin add --from <url>`; there is no `add` subcommand (the verbs are
  `install`, `marketplace`, `list`, `validate`, …), so the advertised plugin
  install has been broken since it was written. Replaced with the real
  marketplace flow, verified end to end.
- **README's HTTP "From Source" example could not start.** It passed only
  ServiceNow credentials, so the fail-closed guard rejected it with
  `refusing to start streamable-http listener without authentication`. Now
  shows `--mcp-static-tokens`, verified to serve 200 with a bearer and 401
  without.

### Changed
- **FastMCP 4.0 is stable** (4.0.0 landed 2026-08-31): pin `4.0.0b2` →
  `>=4.0.3,<5`. `uvx mcp-server-servicenow` no longer needs `--prerelease
  allow` — the flag is gone from the README, `.mcp.json.example`, the plugin
  manifest, `docs/configuration.md` and the release checklist (13 occurrences),
  together with the two workarounds that existed only to resolve a pre-release
  at depth 2: the redundant `fastmcp-slim[client,server]` direct dependency and
  `[tool.uv] prerelease = "allow"` (closes #8).
- `anyio` declared as a direct dependency (async write tools run ServiceNow
  I/O on a worker thread).
- README: "developer data plane that runs alongside the native MCP Server"
  positioning, corrected native comparison table (Zurich P9 / Australia P2,
  Table API excluded, not on PDIs/GCC, OAuth 2.0 via Machine Identity
  Console), new Safety & governance section.
- `server.json` lists every environment variable; `docs/configuration.md`,
  `docs/deployment.md`, `TROUBLESHOOTING.md`, `RELEASING.md` and
  `.env.example` cover the new flags.

## [0.6.1] - 2026-08-13

### Added
- **mypy in CI** — the shipped `py.typed` marker is now backed by an actual
  type check: `mypy src/` runs between format check and tests, with
  `disallow_untyped_defs` across all first-party code and zero suppressions.
  One annotation corrected along the way (`_parse_static_tokens` claims dict
  is `dict[str, Any]`, not `dict[str, str]`) (#9)

### Fixed
- **ROPC OAuth (stdio path)**: the password-grant token request now honors the
  configured `--timeout` instead of hanging indefinitely on an unresponsive
  instance, and the `refresh_token` from the token response is stored and
  used — `refresh_token()` performs a real `grant_type=refresh_token`
  exchange (rotation-aware) and falls back to the password grant only when
  the refresh grant is rejected or errors. New `tests/test_auth_manager.py`
  covers both behaviors (11 tests) (#7)
- Documented that uv/uvx installs need `--prerelease allow` while the FastMCP
  4.0 beta pin is in place (uv only honors pre-release markers in the user's
  own top-level requirement; pip is unaffected). All uvx examples and the
  plugin manifest now carry the flag.

### Changed
- Dependency refresh (Dependabot #6): requests 2.33.0, cryptography 50.0.0,
  pytest 9.0.3, pydantic-settings 2.14.2, pyjwt 2.13.0, urllib3 2.7.0
- Declined community PR #10 (premature FastMCP `>=4.0.0` bump — no stable
  4.0 exists on PyPI yet); #8 remains the tracking issue for the un-pin

## [0.6.0] - 2026-08-12

### Added
- **OAuth 2.1 + PKCE validated end-to-end** on a Zurich PDI: DCR → consent →
  SN login (SSO/MFA-compatible) → ephemeral-loopback callback → per-user tool
  calls. Two Zurich gotchas documented: new PDIs require the
  `snc_basic_auth_api_access` role for REST basic auth, and new OAuth apps
  default to "Securely scoped" tokens which reject Table API calls
- **FastMCP 4.0 (MCP 2026-07-28 protocol)** — the server now speaks both the
  stateless 2026-07-28 MCP revision and the legacy handshake protocol,
  negotiated per connection. Existing stdio clients are unaffected.
  (`fastmcp==4.0.0b2`, exact pin while 4.0 is in beta; `httpx` → `httpx2`,
  pydantic floor 2.12)
- `tests/test_cli.py` — first coverage for the CLI: fail-closed startup,
  static-token/OAuth wiring, arg parsing (18 tests)
- Python 3.13 in the CI matrix and package classifiers
- CI enforces `ruff format --check`; lint rule set pinned in pyproject so
  unpinned ruff upgrades can't break CI
- `uv.lock` is now committed

### Security
- **Fail closed on HTTP**: a non-stdio listener refuses to start unless MCP
  endpoint auth (`MCP_OAUTH_*` or `MCP_STATIC_TOKENS`) is configured
- **Bind localhost by default**: `--host` defaults to `127.0.0.1`; all-interface
  binding is opt-in via `MCP_HOST=0.0.0.0` (the Docker image sets this — the
  container boundary is the isolation)
- PyPI publishing via Trusted Publishing (OIDC), GitHub Actions pinned to
  commit SHAs, broadened `.gitignore` secret patterns, Renovate enabled

### Fixed
- `list_records` `order_by` descending: a leading `-` now emits `ORDERBYDESC`
  instead of being silently discarded by ServiceNow — thanks @Nono-04 (#5,
  fixes #3 reported by @MMunManAIDev)
- Docker image: startup regression from the fail-closed hardening (missing
  MCP auth guidance + loopback binding inside the container)
- MCP server identity now reports the package version instead of FastMCP's
- `aggregate_records` was missing from the plugin agent/command allow-lists,
  making the Stats API tool unreachable from `/servicenow:*` commands
- Plugin manifest version was stuck at 0.4.0
- `server.json`: PKCE requires San Diego+ (2022); Tokyo+ applies to the
  Table API tools, not OAuth

### Changed
- Dropped direct `authlib`/`cryptography` dependencies (never imported;
  FastMCP brings what it needs transitively)

## [0.5.1] - 2026-03-22

### Fixed
- Added MCP Registry ownership tag (`mcp-name`) to README for registry validation
- Pre-publish polish: ruff format (17 files), sdist excludes (960KB → 27KB), PyPI image URL fix, keywords

## [0.5.0] - 2026-03-22

### Added
- **5 MCP Resources** — read-only context for LLM clients, avoiding repeated tool calls:
  - `servicenow://schema/{table_name}` — field definitions (parameterized template)
  - `servicenow://instance` — instance URL, version, user, timezone
  - `servicenow://update-set/current` — active update set name/sys_id
  - `servicenow://cmdb/classes` — CI class hierarchy from sys_db_object
  - `servicenow://help/query-syntax` — encoded query operators reference (static markdown)
- `aggregate_records` tool — COUNT/AVG/MIN/MAX/SUM with GROUP BY + HAVING via Stats API (`/api/now/stats/`)
- `.env.test` support for integration tests (auto-loaded by dotenv, gitignored)
- 7 new integration smoke tests: aggregate_records (with/without group_by) + 5 resource read tests

### Improved
- **Enriched error responses** — 401/403/404 errors now include ServiceNow response body (500 char preview) and diagnostic headers (`X-Is-Logged-In`, `X-Transaction-ID`). Pinpoints exact cause (e.g., `WebServicePolicyValidator`, missing ACL, wrong table name).
- Expanded TROUBLESHOOTING.md with error message interpretation guide

### Fixed
- `aggregate_records` group_by return type — Stats API returns list, wrapped as `{"count": N, "groups": [...]}`
- `__init__.py` version synced with pyproject.toml (was stuck at 0.3.0)

## [0.4.0] - 2026-03-22

### Added
- **FastMCP 3.1.1 upgrade** — bumped from 2.13.2, zero test breakage
- **MultiAuth** — `--mcp-static-tokens` composes OAuth proxy + StaticTokenVerifier for CI/CD
- **Token verification caching** — SHA-256 keyed, 5min TTL, 1000 entry max with auto-eviction
- **HTTP connection pooling** — shared `httpx.AsyncClient` across ServiceNowProvider → TokenVerifier
- **Response size limiting** — `ResponseLimitingMiddleware` at 500KB
- **Tool tags** — all 18 tools tagged `read`/`write` + `table`/`cmdb`/`admin`/`updateset`
- 4 Claude Code skills: CMDB explorer, table explorer, update set reviewer, incident triage
- Claude Code plugin packaging with slash commands and servicenow-admin agent
- README redesign: Mermaid diagram, badges, copy-paste config snippets
- Community health files: CHANGELOG, SECURITY, CODE_OF_CONDUCT, PR template, copilot instructions
- Extracted docs: configuration.md, deployment.md, TROUBLESHOOTING.md

### Security
- Auth header leak prevention (automatic via fastmcp ≥3.0.2 floor)

## [0.3.1] - 2026-02-26

### Fixed
- CLI TypeError on stdio transport (`unexpected keyword argument 'host'`)
- server.json description length for MCP Registry (max 100 chars)

### Added
- MCP Registry schema and automated publish workflow
- `.mcp.json.example` and configuration examples in README

### Changed
- Renamed package to `mcp-server-servicenow`

## [0.3.0] - 2026-02-23

### Added
- OAuth 2.1 + PKCE proxy for per-user ServiceNow auth (Phase 3)
- FastMCP 3.0 migration with dual transport (Phase 2)
- Streamable HTTP transport and Cloud Run deployment
- Security model docs and native vs community comparison
- CI workflow, LICENSE, issue templates, integration tests

## [0.1.0] - 2026-02-07

### Added
- 18-tool ServiceNow MCP server (Phase 1)
- Table API, CMDB, System, Update Sets tool modules
- Basic auth, OAuth password grant, API key authentication
- Pydantic configuration, unit tests
