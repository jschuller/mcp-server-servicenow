# My ServiceNow skills

Skills for [mcp-server-servicenow](https://github.com/jschuller/mcp-server-servicenow), in the open [Agent Skills](https://agentskills.io) format. The guide is [EXTENDING.md](https://github.com/jschuller/mcp-server-servicenow/blob/main/EXTENDING.md), and the precise rules are in the [skill profile](https://github.com/jschuller/mcp-server-servicenow/blob/main/docs/skill-profile.md).

<!-- After your first eval run, show its result here:
![evals](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/<you>/<repo>/main/evals/badge.json)
-->

| Path | What it is |
|------|------------|
| `skills/my-servicenow-skill/` | A plain Agent Skill. Rename the folder and its `name` together |
| `.claude-plugin/plugin.json` | Makes the repository a Claude Code plugin, so `claude plugin eval` can test it. It declares only the skills and the server, pinned to a version |
| `evals/` | Behaviour tests with mocked tools: no instance, no credentials |
| `.github/workflows/validate-skills.yml` | Validator and citation check on every push |
| `.github/workflows/evals.yml` | The eval suite, started by hand, with your own Claude credential |

## 1. Write the skill

Edit `skills/my-servicenow-skill/SKILL.md`:
- **The description** says what it does, then the words people type when they need it.
- **The metadata** declares the tables and roles, plus `io.github.jschuller/servicenow-writes` if it calls a write tool.
- **The body** covers what a 403, an empty result or a missing field means.

Then check it:

```bash
uvx mcp-server-servicenow==0.9.0 --validate-skills . --strict
```

## 2. Test it with mocked tools

```bash
uvx mcp-server-servicenow==0.9.0 --eval-mocks .
```

This writes `evals/mocks/servicenow/`:
- `_tools.json`, the server's real tool list;
- default mocks;
- an empty fixture for every table you declared.

The defaults behave like a least-privilege identity: rows come from `fixtures/<table>.json`, aggregates are refused with a 401, and the schema with a 403. Put invented sample rows in the fixtures, never records from a real instance. A case can override any mock in its own `mocks/` folder. Commit `evals/mocks/`, including `.replay/` if it appears.

Write a case per job the skill does (`evals/<case>/prompt.md` plus `graders/`), then run the cases with your skills, and again with the bare tools:

```bash
claude plugin eval . --runs 3 --ablation none --json evals/results.json
uvx mcp-server-servicenow==0.9.0 --eval-baseline . ../tools-only
claude plugin eval ../tools-only --runs 3 --ablation none --json evals/baseline.json
```

The second run is what tells you whether the skill helps. A case the bare tools already pass shows the skill adds nothing there. Runs use your Claude plan's allowance or your API key.

## 3. Publish results with the skill

```bash
uvx mcp-server-servicenow==0.9.0 --eval-summary evals/results.json --baseline evals/baseline.json --badge evals/badge.json > RESULTS.md
```

Commit `RESULTS.md` and `evals/badge.json`, then tag the commit. Don't commit the raw result files: they record paths on your machine. Anyone can re-run the suite from that tag, because the mocks and cases are in the repository.

A run in GitHub Actions (`evals.yml`) is labelled **CI-run** and links its log. A local run is labelled **self-reported**. The workflow needs one repository secret:
- **`ANTHROPIC_API_KEY`**: billed per call.
- **`CLAUDE_CODE_OAUTH_TOKEN`**: from `claude setup-token`; it counts against your Claude subscription.

## 4. Share it

- Add the topic **`servicenow-mcp-skill`** to this repository (About → Topics), so people find it.
- Post it in [Discussions › Skills](https://github.com/jschuller/mcp-server-servicenow/discussions/categories/skills) with your validator output and a link to `RESULTS.md`.
- Install: `npx skills add <you>/<repo>`, or copy `skills/*` into your client's skills folder.

Keep the plugin wrapper to skills and the server. The validator refuses hooks, agents, commands and scripts, because `claude plugin eval` runs a plugin's code as whoever evaluates it.
