# mcp-servicenow: notes for AI sessions

This repository is public (jschuller/mcp-server-servicenow): names and paths only, never a secret value, an instance name
or an internal URL in code, docs, commits or PRs. Releases: `RELEASING.md`; tests: `uv run --frozen --extra dev pytest`.

- **MLflow** (`~/src/homelab-governance/MLFLOW_STANDARD.md`): writes evaluation runs to `mcp-servicenow-evals`, one run per
  `claude plugin eval` results folder, with `scripts/log_evals_to_mlflow.py` and the `homelab-service` login through
  `with-secrets` (launch line in `RELEASING.md`, "Behaviour evals"); checked by
  `~/.local/share/observability/current/ops/mlflow/mlflow conventions --project mcp-servicenow`.
