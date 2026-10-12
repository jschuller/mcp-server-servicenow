## Eval results

| | |
|---|---|
| Cases passed | 2 / 2 (threshold 1) |
| Suite score | 1.00 |
| Δ vs tools only | +0.50 |
| Δ vs no plugin | +0.50 |
| Model / judge | claude-sonnet-5-5 / claude-haiku-5-5 |
| Runs per case | 3 |
| Claude Code | 2.1.296 |
| Mocks from | mcp-server-servicenow 0.9.0 |
| Cost (list-price estimate) | $0.89 |
| Started | 2026-10-12T20:20:16.982Z |
| Commit | 906f116c985c |
| Kind | self-reported |

| Case | Score | Tools only | Δ vs tools | Δ vs no plugin |
|---|---|---|---|---|
| trend-aggregate-denied | 1.00 | 0.00 | +1.00 | +1.00 |
| write-unavailable | 1.00 | 1.00 | +0.00 | +0.00 |

- **Δ vs tools only:** the same cases with this server's tools and no skills (`--eval-baseline`), scored without the graders that check a skill fired. It is what the skills add.
- **Δ vs no plugin:** what `claude plugin eval` reports. The mocked tools are absent without the plugin, so it overstates what the skills add.

Reproduce from this commit: `claude plugin eval . --ablation with-without --model claude-sonnet-5-5 --judge-model claude-haiku-5-5 --runs 3`

Tools-only baseline: `mcp-server-servicenow --eval-baseline . ../tools-only && claude plugin eval ../tools-only --ablation none --model claude-sonnet-5-5 --judge-model claude-haiku-5-5 --runs 3`

