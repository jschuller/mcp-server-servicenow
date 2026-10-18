# Example: change impact and SLA review

Two read-only skills for mcp-server-servicenow, written from scratch as an example of the [skill profile](https://github.com/jschuller/mcp-server-servicenow/blob/main/docs/skill-profile.md). They need `itil` (plus `snc_read_only` for a read-only identity).

| Skill | What it does |
|-------|--------------|
| `assessing-change-impact` | A change's affected CIs, overlapping changes on those CIs, and incidents on them after the change |
| `reviewing-sla-definitions` | Overlapping and unused SLA definitions, and breach rates per definition |

Install: copy `skills/*` into your client's skills folder (for Claude Code, `~/.claude/skills/` or a project's `.claude/skills/`), with mcp-server-servicenow connected. Or load this folder as a Claude Code plugin: `claude --plugin-dir examples/change-impact`.

Validate: `uvx mcp-server-servicenow==0.9.2 --validate-skills . --strict` (the skills, the plugin wrapper and its eval files). Behaviour tests with mocked tools: `claude plugin eval .` (uses your Claude plan's allowance).
- **Results:** [RESULTS.md](RESULTS.md), from a pinned run. It includes what the skills add over the bare tools, case by case.
