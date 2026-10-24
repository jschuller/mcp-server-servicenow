# Write your own ServiceNow skills

mcp-server-servicenow gives an AI assistant tools to read your instance (tables, CMDB, update sets, schema) and ships four skills for Now Platform jobs (tables, access, update sets, CMDB data quality). Your organisation knows things those skills don't: your conventions, your CMDB classes, how you run change. Write them down as skills of your own.

A skill is a folder with a `SKILL.md` file, in the open [Agent Skills](https://agentskills.io) format. Claude Code, Claude, Codex, VS Code with Copilot, Cursor, opencode, Gemini CLI and pi all load skill folders natively. This project adds what you need to write, check, test and share ServiceNow skills:
- a short profile;
- a validator and a GitHub Action;
- eval mocks of the server's tools and a results summary;
- a template and examples.

It doesn't host your skills or vet them.

## What to write

The skills shipped in the server cover the Now Platform. Everything else is yours to write, and the most useful skills are the ones only your organisation could write:
- **Applications:** IT service management beyond the [incident triage example](examples/incident-triage/), change and problem, HR service delivery, customer service, security operations, risk and compliance, portfolio management. ServiceNow ships MCP servers for some of these. A skill on this server suits teams without those servers, and work that needs raw table access.
- **Your conventions:** naming, assignment rules, required fields, your CMDB classes and data owners, your promotion checklist.
- **Your audits:** the checks your platform team runs every release.

Ideas and requests go in [Discussions › Ideas](https://github.com/jschuller/mcp-server-servicenow/discussions/categories/ideas).

## Start from the template

1. Create a repository from the [template repository](https://github.com/jschuller/servicenow-skills-template) with GitHub's "Use this template" button, or copy [`examples/template/`](examples/template/). A private repository works the same way.
2. Rename `skills/my-servicenow-skill/`, the `name` in its `SKILL.md` and the skill name in `evals/my-first-case/graders/skill-fired.md` together. The validator warns when a grader names a skill that isn't there.
3. Write the skill:
   - **The description:** what the skill does, then the words a user would type when they need it. Agents choose skills by their description.
   - **Tables and roles:** each table it reads, and the least role that reads it. Put the same lists in the two metadata keys:
     ```yaml
     metadata:
       io.github.jschuller/servicenow-roles: "itil snc_read_only"
       io.github.jschuller/servicenow-tables: "change_request task_ci incident"
     ```
   - **Writes:** a skill that calls a write tool names it in a third key, e.g.
     `io.github.jschuller/servicenow-writes: "create_record"`, and tells the agent to ask
     before writing. Leave the key out for a read-only skill.
   - **Tool calls:** in code blocks, written as calls, e.g. `list_records(table_name="incident", query="...", fields="...")`. The validator checks them against the server's rules.
   - **Denials:** what a 403 means ("not assessable with this identity"), and what 0 rows or missing fields mean ("possibly hidden by an ACL").
   - **References:** long material goes in `references/*.md`.
   - **Instructions only:** no `hooks`, `allowed-tools` or `shell` fields, and no `` !`command` `` shell injection. Claude Code runs those as the user, so the validator refuses them.

[`examples/incident-triage/`](examples/incident-triage/) and [`examples/change-impact/`](examples/change-impact/) show complete skills, each with evals. The precise rules are in the [skill profile](docs/skill-profile.md). The official [skill-creator](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/skill-creator) plugin for Claude Code helps with drafting and with tuning the description.

## Check it

```bash
uvx mcp-server-servicenow==0.9.2 --validate-skills . --strict
```

The command runs offline. It prints each skill's `sha256:` digest and every finding. Errors cover anything that makes a skill broken or unsafe:
- scripts, symlinks or binary files, and symlinked folders anywhere in the repository;
- frontmatter that runs code or pre-approves tools (`hooks`, `allowed-tools`, `shell`), and `` !`command` `` shell injection;
- frontmatter that Claude Code could read differently, such as a value continuing in column 0, a `---` inside the block, or a tab ([layout rules](docs/skill-profile.md#frontmatter-layout));
- `SKILL.md` and the plugin's files spelled in another letter case (`skill.md`), which Claude Code loads on macOS and Windows;
- links that leave the skill;
- undeclared tables;
- queries the server would refuse.

Warnings cover what a reviewer should look at:
- calls to write tools the skill doesn't declare;
- links outside ServiceNow's documentation;
- anything that looks like a credential.

It also checks the plugin wrapper (`.claude-plugin/plugin.json`):
- **The manifest** may declare only metadata, the skills and one server. Any other key is an error, and so are the folders Claude Code loads as code (`hooks/`, `agents/`, `commands/`, `bin/`, `workflows/` and the rest), a `package.json`, and uv settings.
- **The server** must run `uvx mcp-server-servicenow[==version]` with the package first. Only `--read-only`, `--debug`, `--allow-js-queries` or `--skills on|off` may follow it, and `env` may set only this server's `SERVICENOW_*` settings. Credentials, the instance URL and the token URL must come from the user's environment, as `${NAME}` or `${NAME:-}` with no default value, so a skills repository can't send your credentials to a host it chooses.
- **The evals:** it warns when `evals/mocks/<server>/_tools.json` no longer matches the server's tools, and when a grader names a skill, plugin or server that isn't there.

With `--strict`, warnings fail too, such as a remote server, `--allow-js-queries` or an audit log written to a file.

In GitHub, the template's workflow runs the same check and a citation check on pull requests and pushes to main, using the Action:

```yaml
- uses: jschuller/mcp-server-servicenow/actions/validate-skills@66ba9254971e36dad67d3c0f609d9161d29d0d1c # v0.9.0
  with:
    path: .
    server-version: "0.9.2"
    strict: "true"
```

The Action runs the validator from `server-version` and its own citation check, so its pinned release can trail the server's; the citation check follows the pin.

## Test it

### On a developer instance

Point mcp-server-servicenow at a personal developer instance, with an identity that holds exactly the roles you declared, and ask the questions your skill is for. Anything that needs more access shows up as a 403, which the skill should report as "not assessable", not as an empty answer.

### With mocked tools

[`claude plugin eval`](https://code.claude.com/docs/en/plugin-evals) runs your skill in Claude Code against mocked tools. It needs no instance and no instance credentials, so anyone can re-run your results.

1. **Generate the mocks:** `uvx mcp-server-servicenow==0.9.2 --eval-mocks .` writes `evals/mocks/servicenow/`:
   - `_tools.json`: the server's real tool list for that version;
   - default mocks modelled on a least-privilege identity: rows from `fixtures/<table>.json`, aggregates refused with a 401, the schema with a 403;
   - an empty fixture for every table your skills declare.

   Re-running it refreshes `_tools.json` and keeps everything you edited.
2. **Fill the fixtures** with invented rows that exercise the skill, including the awkward cases: a hidden field, an empty table, a denial. A case can override any mock in its own `mocks/` folder.
3. **Write cases:** `evals/<case>/prompt.md` (what a user would ask) plus `graders/`. Prefer deterministic graders (`tool_used`, `regex`), and keep `llm` graders to short, concrete PASS/FAIL rules. Add one case where the skill must not fire.
4. **Commit, then run the cases with your skills and with the bare tools:**
   ```bash
   claude plugin eval . --trust-plugin --runs 3 --ablation none --json evals/results.json
   uvx mcp-server-servicenow==0.9.2 --eval-baseline . ../tools-only
   claude plugin eval ../tools-only --trust-plugin --runs 3 --ablation none --json evals/baseline.json
   ```
   - `--eval-baseline` copies your plugin without its skills: same name, same server, same cases and mocks. It replaces the copy an earlier run wrote, so re-run it whenever a case changes.
   - `--trust-plugin` answers the trust prompt, which `--json` can't show. Pass it only for your own repository.
   - Runs count against your Claude plan's usage or your API bill.

Mocks are not an instance. They don't apply queries (`list_records` returns the whole fixture) or add the missing-field `warning`, and a tool with no mock is unavailable in the run.

Read the score next to the tools-only score. The eval tool's own Δ compares your plugin with no plugin at all, and without the plugin the mocked tools are absent too, so that Δ overstates what the skills add. A study of agent skills (SkillsBench) found that skills authors write for themselves often add nothing. Our own examples show the same: on the change-collision case the bare tools already score 1.00, and the no-plugin Δ of +1.00 says nothing about the skill.

## Install it

Copy the skill folders where your client looks for skills, with mcp-server-servicenow connected:
- Claude Code: `~/.claude/skills/`, or a project's `.claude/skills/`.
- Other clients: see their skills documentation.

Two shortcuts:
- **The `skills` command-line tool** ([vercel-labs/skills](https://github.com/vercel-labs/skills)): `npx skills add <owner>/<repo>` searches a repository for skill folders and installs them for Claude Code, Codex, Cursor and other clients.
  - Pin the tool's version, e.g. `npx skills@1.7.0`.
  - Add `--copy` for real copies instead of symlinks.
  - Tested with 1.7.0 on this template and the example.
- **Claude Code plugin:** Claude Code can load the whole repository as a plugin.

## Share it

- **Your repository, your licence.** Publish the skills in your own repository, under the licence you choose. This project doesn't host or republish them.
- **Results live with the skill.** Write `RESULTS.md` from a finished run, then commit it with the mocks and cases and tag the commit:
  ```bash
  uvx mcp-server-servicenow==0.9.2 --eval-summary evals/results.json --baseline evals/baseline.json --badge evals/badge.json > RESULTS.md
  ```
  The summary records what the skills add over the bare tools, case by case, and the models, the Claude Code version, the server version the mocks came from, the commit, and a command to reproduce the run. It refuses a partial run, a run where some runs ended in an error (a usage limit scores 0), and a baseline made with other models. Commit before the run: the summary marks a commit with uncommitted edits. There are two kinds of results:
  - **CI-run:** produced by the template's `evals.yml` in GitHub Actions; it links the public log. Commit the `RESULTS.md` and badge from the run's `eval-results` artifact.
  - **Self-reported:** run anywhere else.

  Nobody verifies either; the committed mocks make both reproducible. Commit `RESULTS.md`, not the raw result files: those record paths on your machine.
- **Be findable:** add the GitHub topic `servicenow-mcp-skill` to your repository.
- **Tell people about it** in [Discussions › Skills](https://github.com/jschuller/mcp-server-servicenow/discussions/categories/skills). The form asks for:
  - the repository and a tag;
  - the licence;
  - the roles and tables;
  - the ServiceNow releases you tested;
  - the validator's output;
  - optionally, your `RESULTS.md`.
- **No endorsement.** We don't vet or endorse shared skills or their results beyond what the validator checks.
- **Keep private skills private.** Skills that describe your organisation's instance can stay in a private repository and still use the Action.

## Your content, your responsibility

- You are responsible for the rights to what you publish.
- Write in your own words, and cite ServiceNow's documentation by link: the readable page plus the [ServiceNowDocs](https://github.com/ServiceNow/ServiceNowDocs) file at the commit you read. The citation check tells you when a cited page changes or disappears.
- Don't copy gated material, such as the Best Practices portal, Support (KB) articles, training courses or partner content. At most, cite a public URL.
- Never include customer data, real record contents, instance names you don't own, or credentials.

## Security

A skill is instructions your agent will follow, so treat skills from others like code from others:
- read them before installing;
- pin them by commit or by the validator's digest;
- prefer read-only skills.

To re-run someone else's evals, run the validator with `--strict` on their repository first. `claude plugin eval` runs a plugin's hooks, agents and servers as you, and a repository that passes has none of those: its wrapper declares only skills and this server, and its skills carry no hooks, pre-approved tools or shell injection. The validator is a check, not a sandbox, so still read what you run. Never pass `--scaffold`, `--allow-real-servers` or `--mocks off` to a suite you didn't write. If you're unsure, run it in a container or a CI runner.

Hosts treat skills served over MCP as untrusted input (SEP-2640). Keep skills that write to an instance explicit about it, and keep the identity they run with to the least roles that do the job.
