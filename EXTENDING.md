# Write your own ServiceNow skills

mcp-server-servicenow gives an AI assistant tools to read your instance (tables, CMDB, update sets, schema) and ships five skills that teach common jobs. Your organisation knows things those skills don't: your conventions, your CMDB classes, how you run change. Write them down as skills of your own.

A skill is a folder with a `SKILL.md` file, in the open [Agent Skills](https://agentskills.io) format. Claude Code, Claude, Codex, VS Code with Copilot, Cursor, opencode, Gemini CLI and pi all load skill folders natively. This project adds a short profile for ServiceNow skills, a validator, a GitHub Action, a template and an example. It doesn't host your skills.

## Start from the template

1. Copy [`examples/template/`](examples/template/) into a new repository, or into a private one for your organisation.
2. Rename `skills/my-servicenow-skill/` and the `name` in its `SKILL.md` together.
3. Write the skill:
   - **The description:** what the skill does, then the words a user would type when they need it. Agents choose skills by their description.
   - **Tables and roles:** each table it reads, and the least role that reads it. Put the same lists in the two metadata keys:
     ```yaml
     metadata:
       io.github.jschuller/servicenow-roles: "itil snc_read_only"
       io.github.jschuller/servicenow-tables: "change_request task_ci incident"
     ```
   - **Tool calls:** in code blocks, written as calls, e.g. `list_records(table_name="incident", query="...", fields="...")`. The validator checks them against the server's rules.
   - **Denials:** what a 403 means ("not assessable with this identity"), and what 0 rows or missing fields mean ("possibly hidden by an ACL").
   - **References:** long material goes in `references/*.md`.

[`examples/change-impact/`](examples/change-impact/) shows two complete skills. The precise rules are in the [skill profile](docs/skill-profile.md). The official [skill-creator](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/skill-creator) plugin for Claude Code helps with drafting and with tuning the description.

## Check it

```bash
uvx mcp-server-servicenow --validate-skills skills --strict
```

The command runs offline. It prints each skill's `sha256:` digest and every finding. Errors cover anything that makes a skill broken or unsafe:
- scripts, symlinks or binary files;
- links that leave the skill;
- undeclared tables;
- queries the server would refuse.

Warnings cover what a reviewer should look at:
- calls to write tools;
- links outside ServiceNow's documentation;
- anything that looks like a credential.

In GitHub, the template's workflow runs the same check and a citation check on every push, using the Action:

```yaml
- uses: jschuller/mcp-server-servicenow/actions/validate-skills@v0.9.0
  with:
    path: skills
    server-version: "0.9.0"
    strict: "true"
```

## Test it on a developer instance

- **Live instance.** Point mcp-server-servicenow at a personal developer instance, with an identity that holds exactly the roles you declared, and ask the questions your skill is for. Anything that needs more access shows up as a 403, which the skill should report as "not assessable", not as an empty answer.
- **Mocked tools (Claude Code only, optional).** The template is also a Claude Code plugin with one example case: `claude plugin eval .` runs your skill against invented sample data, with no instance and no credentials. These runs count against your Claude plan's usage or your API bill.

## Install it

Copy the skill folders where your client looks for skills, with mcp-server-servicenow connected:
- Claude Code: `~/.claude/skills/`, or a project's `.claude/skills/`.
- Other clients: see their skills documentation.

Claude Code can also load the whole repository as a plugin.

## Share it

- **Your repository, your licence.** Publish the skills in your own repository, under the licence you choose. This project doesn't host or republish them.
- **Tell people about it** in [Discussions › Skills](https://github.com/jschuller/mcp-server-servicenow/discussions/categories/skills). The form asks for:
  - the repository;
  - a version or tag;
  - the licence;
  - the roles and tables;
  - the ServiceNow releases you tested;
  - the validator's output.
- **No endorsement.** We don't vet or endorse shared skills beyond what the validator checks.
- **Keep private skills private.** Skills that describe your organisation's instance can stay in a private repository and still use the Action.

## Your content, your responsibility

- You are responsible for the rights to what you publish.
- Write in your own words, and cite ServiceNow's documentation by link: the readable page plus the [ServiceNowDocs](https://github.com/ServiceNow/ServiceNowDocs) file at the commit you read. The citation check tells you when a cited page changes or disappears.
- Don't copy gated material, such as the Best Practices portal, Support (KB) articles, training courses or partner content. At most, cite a public URL.
- Never include customer data, real record contents, instance names you don't own, or credentials.

## Security

A skill is instructions your agent will follow, so treat skills from others like code from others:
- read them before installing;
- pin them by tag or by the validator's digest;
- prefer read-only skills.

Hosts treat skills served over MCP as untrusted input (SEP-2640). Keep skills that write to an instance explicit about it, and keep the identity they run with to the least roles that do the job.
