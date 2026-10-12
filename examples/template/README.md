# Template: your own ServiceNow skills

Copy this folder to start a repository of skills for [mcp-server-servicenow](https://github.com/jschuller/mcp-server-servicenow). The guide is [EXTENDING.md](https://github.com/jschuller/mcp-server-servicenow/blob/main/EXTENDING.md).

| Path | What it is |
|------|------------|
| `skills/my-servicenow-skill/` | A plain Agent Skill; rename the folder and the `name` together |
| `.github/workflows/validate-skills.yml` | Runs the validator and the citation check on every push |
| `.claude-plugin/plugin.json` | Optional: makes the folder a Claude Code plugin, so `claude plugin eval .` can test it |
| `evals/` | Optional: one behaviour test with mocked tools (no instance, no credentials) |

Check locally: `uvx mcp-server-servicenow --validate-skills skills --strict`.
