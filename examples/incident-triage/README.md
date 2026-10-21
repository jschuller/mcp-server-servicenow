# Example: incident triage (ITSM)

An application skill for mcp-server-servicenow, kept outside the server on purpose. The server's own skills cover the Now Platform (tables, access, update sets, CMDB data quality). Incident, problem and change management belong to IT Service Management, where ServiceNow also ships its own ITSM MCP server. This skill shipped inside the server up to 0.8.0 and moved here in 0.9.0. It is the fullest example of the [skill profile](https://github.com/jschuller/mcp-server-servicenow/blob/main/docs/skill-profile.md):
- declared tables, roles and write tools;
- trend reports that fall back to counting rows when the Aggregate API is refused;
- what a 403, an empty result or a hidden field means.

| Skill | What it does |
|-------|--------------|
| `triaging-incidents` | Assess, find related incidents and CIs, recommend assignment, create incidents (asks first), and report trends |

It needs `itil`. Add `snc_read_only` for a read-only identity; the skill then proposes changes instead of making them.

- **Install:**
  - with `npx skills add jschuller/mcp-server-servicenow --skill triaging-incidents`;
  - or copy `skills/triaging-incidents` into your client's skills folder (for Claude Code, `~/.claude/skills/` or a project's `.claude/skills/`), with mcp-server-servicenow connected;
  - or load this folder as a Claude Code plugin: `claude --plugin-dir examples/incident-triage`.
- **Validate:** `uvx mcp-server-servicenow==0.9.2 --validate-skills . --strict` (the skills, the plugin wrapper and its eval files).
- **Behaviour tests with mocked tools:** `claude plugin eval .`. This uses your Claude plan's allowance.
- **Results:** [RESULTS.md](RESULTS.md), from a pinned run. It includes what the skills add over the bare tools, case by case.
