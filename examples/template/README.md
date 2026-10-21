# My ServiceNow skills

Skills for [mcp-server-servicenow](https://github.com/jschuller/mcp-server-servicenow), in the open [Agent Skills](https://agentskills.io) format. The guide is [EXTENDING.md](https://github.com/jschuller/mcp-server-servicenow/blob/main/EXTENDING.md), and the precise rules are in the [skill profile](https://github.com/jschuller/mcp-server-servicenow/blob/main/docs/skill-profile.md).

<!-- After your first eval run, show its result here:
![evals](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/<you>/<repo>/main/evals/badge.json)
-->

| Path | What it is |
|------|------------|
| `skills/my-servicenow-skill/` | A plain Agent Skill. Rename the folder, its `name` and the name in `evals/my-first-case/graders/skill-fired.md` together |
| `.claude-plugin/plugin.json` | Makes the repository a Claude Code plugin, so `claude plugin eval` can test it. It declares only the skills and the server, pinned to a version |
| `evals/` | Behaviour tests with mocked tools: no instance, no credentials |
| `.github/workflows/validate-skills.yml` | Validator and citation check on pull requests and pushes to main |
| `.github/workflows/evals.yml` | The eval suite, started by hand, with your own Claude credential |
| `LICENSE` | MIT. Put your own name in it, or replace it with the licence you choose |

## 1. Write the skill

Edit `skills/my-servicenow-skill/SKILL.md`:
- **The description** says what it does, then the words people type when they need it.
- **The metadata** declares the tables and roles, plus `io.github.jschuller/servicenow-writes` if it calls a write tool.
- **The body** covers what a 403, an empty result or a missing field means.
- **The licence:** put your name in `LICENSE` and in the skill's `author`. If you choose another licence, change `LICENSE` and the skill's `license` together.

Then check it:

```bash
uvx mcp-server-servicenow==0.9.2 --validate-skills . --strict
```

## 2. Test it with mocked tools

```bash
uvx mcp-server-servicenow==0.9.2 --eval-mocks .
```

This writes `evals/mocks/servicenow/`:
- `_tools.json`, the server's real tool list;
- default mocks;
- an empty fixture for every table you declared.

The defaults behave like a least-privilege identity: rows come from `fixtures/<table>.json`, aggregates are refused with a 401, and the schema with a 403. Put invented sample rows in the fixtures, never records from a real instance. A case can override any mock in its own `mocks/` folder. Commit `evals/mocks/`, including `.replay/` if it appears.

Mocks are not an instance:
- **They don't apply queries.** `list_records` returns the whole fixture, so put in it only the rows the question should find, plus the fields the skill filters on.
- **They don't add the missing-field `warning`.** Write a case-level mock if a case needs it.
- **Only mocked tools exist in a run.** A tool with no `<tool>.md` is unavailable, so add a mock for each tool your skill calls.

Write a case per job the skill does (`evals/<case>/prompt.md` plus `graders/`). Commit your changes, so the results name the commit they came from. Then run the cases with your skills, and again with the bare tools:

```bash
claude plugin eval . --trust-plugin --runs 3 --ablation none --json evals/results.json
uvx mcp-server-servicenow==0.9.2 --eval-baseline . ../tools-only
claude plugin eval ../tools-only --trust-plugin --runs 3 --ablation none --json evals/baseline.json
```

`--trust-plugin` answers the trust prompt, which `--json` can't show. Pass it only for your own repository. `--eval-baseline` replaces the copy an earlier run wrote, so re-run it whenever you change a case.

The second run is what tells you whether the skill helps. A case the bare tools already pass shows the skill adds nothing there. Runs use your Claude plan's allowance or your API key.

## 3. Publish results with the skill

```bash
uvx mcp-server-servicenow==0.9.2 --eval-summary evals/results.json --baseline evals/baseline.json --badge evals/badge.json > RESULTS.md
```

It refuses a run that stopped early or had runs end in an error, such as a usage limit, since those score 0. Commit `RESULTS.md` and `evals/badge.json`, then tag the commit. Don't commit the raw result files: they record paths on your machine. Anyone can re-run the suite from that tag, because the mocks and cases are in the repository.

A run in GitHub Actions (`evals.yml`, under Actions › Evals › Run workflow) is labelled **CI-run** and links its log. Download its `eval-results` artifact, then commit the `RESULTS.md` and `evals/badge.json` from it. A local run is labelled **self-reported**. The workflow needs one repository secret:
- **`ANTHROPIC_API_KEY`**: billed per call.
- **`CLAUDE_CODE_OAUTH_TOKEN`**: from `claude setup-token`; it counts against your Claude subscription.

## 4. Share it

- Add the topic **`servicenow-mcp-skill`** to this repository (About → Topics), so people find it.
- Post it in [Discussions › Skills](https://github.com/jschuller/mcp-server-servicenow/discussions/categories/skills) with your validator output and a link to `RESULTS.md`.
- Install: `npx skills@1.7.0 add <you>/<repo>`, or copy `skills/*` into your client's skills folder.

Keep the plugin wrapper to skills and the server, and the skills to instructions. The validator refuses hooks, agents, commands, scripts, pre-approved tools and `` !`command` `` shell injection, because `claude plugin eval` and the skills' users run that code as themselves.
