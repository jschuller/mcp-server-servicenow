"""Log one ``claude plugin eval`` results folder to MLflow as one evaluation run.

Reads ``evals/results/<folder>/aggregate-result.json`` (default: the newest folder) and
writes one run into the experiment ``mcp-servicenow-evals``, following the homelab MLflow
standard (rules E, J, V and W):

- the experiment is created if missing, with its description and ``homelab.*`` tags;
- the run is named ``skill-evals <folder>`` and tagged with the project, the job name,
  the source (commit, script, ``LOCAL``) and the user;
- the case set is a dataset input: case names, their folders and a digest of their
  definitions (no prompt text, no transcript, no local path);
- per-arm scores (``<arm>.pass_rate``, run counts, mean score, cost) and the suite's
  totals are metrics, with ``duration_s`` and ``ok`` (1 when the run finished and no
  case run ended in an error); per-case results are the artifact ``evals/cases.json``.

A folder that already has a finished run (tag ``evals.results``) is skipped, so running it
twice logs once. MLflow is reached only through the environment:

    MLFLOW_TRACKING_URI=http://127.0.0.1:5001 MLFLOW_TRACKING_USERNAME=homelab-service \\
      with-secrets MLFLOW_TRACKING_PASSWORD=svc/observability/mlflow-service-password -- \\
      uv run --frozen --isolated --group mlflow python scripts/log_evals_to_mlflow.py

``--dry-run`` prints what would be logged and contacts nothing. Exit codes: 0 logged or
already logged, 1 MLflow failed, 2 bad input (no folder, unreadable result, no URI).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

EXPERIMENT = "mcp-servicenow-evals"
PROJECT = "mcp-servicenow"
JOB = "skill-evals"
SOURCE_NAME = "scripts/log_evals_to_mlflow.py"
RESULTS_TAG = "evals.results"
RESULT_FILE = "aggregate-result.json"
DATASET_NAME = "skill-eval-cases"
CASES_ARTIFACT = "evals/cases.json"
DEFAULT_USER = "homelab-service"
REPO = Path(__file__).resolve().parent.parent
DEFAULT_RESULTS_DIR = REPO / "evals" / "results"

# A results folder name, as `claude plugin eval` writes them (2026-10-18T23-16-57-156Z).
# It goes into a search filter, so nothing that could close the quoted value.
FOLDER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
ARM_RE = re.compile(r"[^a-z0-9_]+")

EXPERIMENT_TAGS = {
    "mlflow.note.content": (
        "Skill evaluations of mcp-servicenow (repository jschuller/mcp-server-servicenow), "
        "written by scripts/log_evals_to_mlflow.py: one run per `claude plugin eval` results "
        "folder (evals/results/<timestamp>), named `skill-evals <folder>`. Read a run: the "
        "metric `with.pass_rate` is the share of case runs that passed with the plugin's "
        "skills (other arms, such as `without`, get their own prefix), `overall_pass_rate` "
        "and `cases_passed` are the suite's totals, `cost_usd` its list-price cost, `ok` is 1 "
        "when the suite finished with no errored run. Params give the models and the Claude "
        "Code version; the dataset input is the case set (names and a digest); the artifact "
        "evals/cases.json has per-case results."
    ),
    "homelab.project": PROJECT,
    "homelab.kind": "evaluation",
    "mlflow.experimentKind": "genai_development",
}


class InputError(Exception):
    """A results folder that can't be read or isn't a ``claude plugin eval`` result."""


@dataclass
class Plan:
    """Everything one run logs, built from a results folder without touching MLflow."""

    folder: str
    run_name: str
    tags: Dict[str, str]
    params: Dict[str, str]
    metrics: Dict[str, float]
    dataset: Dict[str, Any]
    cases: List[Dict[str, Any]] = field(default_factory=list)


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _mean(values: List[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def newest_folder(results_dir: Path) -> Path:
    """The newest results folder: names are UTC timestamps, so the last in sort order."""
    if not results_dir.is_dir():
        raise InputError(f"{results_dir}: no such results directory")
    folders = sorted(
        p
        for p in results_dir.iterdir()
        if p.is_dir() and FOLDER_RE.match(p.name) and (p / RESULT_FILE).is_file()
    )
    if not folders:
        raise InputError(f"{results_dir}: no folder with an {RESULT_FILE}")
    return folders[-1]


def resolve_folder(folder: Optional[str], results_dir: Path) -> Path:
    if folder is None:
        return newest_folder(results_dir)
    path = Path(folder)
    if not path.is_dir():
        path = results_dir / folder
    if not path.is_dir():
        raise InputError(f"{folder}: no such results folder")
    return path


def load_result(folder: Path) -> Dict[str, Any]:
    if not FOLDER_RE.match(folder.name):
        raise InputError(f"{folder.name}: not a results folder name")
    path = folder / RESULT_FILE
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InputError(f"{path}: cannot read ({exc})") from exc
    if not isinstance(result, dict) or result.get("schemaVersion") != 1:
        raise InputError(f"{path}: not a claude plugin eval result (schemaVersion 1)")
    for key in ("suite", "aggregates"):
        if not _is(result.get(key), dict):
            raise InputError(f"{path}: {key} is not an object")
    cases = result.get("cases")
    if not _is(cases, list) or not all(
        isinstance(c, dict)
        and isinstance(c.get("name"), str)
        and _is(c.get("arms"), dict)
        and all(_is(r, list) for r in (c.get("arms") or {}).values())
        and _is(c.get("aggregates"), dict)
        and _is(c.get("graders"), list)
        for c in cases or []
    ):
        raise InputError(f"{path}: cases is not a list of named cases with arms")
    return result


def _is(value: Any, kind: type) -> bool:
    """Absent (None) or of the given kind: a field the writer may leave out."""
    return value is None or isinstance(value, kind)


def _runs(case: Dict[str, Any], arm: str) -> List[Dict[str, Any]]:
    return [r for r in (case.get("arms") or {}).get(arm) or [] if isinstance(r, dict)]


def _arm_names(cases: List[Dict[str, Any]]) -> List[str]:
    names: List[str] = []
    for case in cases:
        for arm in case.get("arms") or {}:
            if arm not in names:
                names.append(arm)
    return names


def _metric_arm(arm: str) -> str:
    return ARM_RE.sub("_", str(arm).lower()).strip("_") or "arm"


def _arm_stats(runs: List[Dict[str, Any]]) -> Dict[str, float]:
    """Counts, pass rate, mean score and turns, and cost, over one arm's case runs."""
    stats: Dict[str, float] = {
        "runs": float(len(runs)),
        "runs_passed": float(sum(1 for r in runs if r.get("passed") is True)),
        "runs_errored": float(sum(1 for r in runs if r.get("error"))),
    }
    if runs:
        stats["pass_rate"] = stats["runs_passed"] / len(runs)
    for key, source in (("score_mean", "score"), ("turns_mean", "turns")):
        mean = _mean(
            [v for v in (_number(r.get(source)) for r in runs) if v is not None]
        )
        if mean is not None:
            stats[key] = mean
    for key, source in (("cost_usd", "costUsd"), ("judge_cost_usd", "judgeCostUsd")):
        costs = [v for v in (_number(r.get(source)) for r in runs) if v is not None]
        if costs:
            stats[key] = sum(costs)
    return stats


def _case_dir(case: Dict[str, Any]) -> str:
    """The case's folder, repo-relative; an absolute or escaping path keeps only its name."""
    value = case.get("dir")
    if not isinstance(value, str) or not value:
        return ""
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        return path.name
    return path.as_posix()


def _grader_ids(case: Dict[str, Any]) -> List[Dict[str, Any]]:
    graders = []
    for g in case.get("graders") or []:
        if isinstance(g, dict) and isinstance(g.get("name"), str):
            graders.append(
                {
                    "name": g["name"],
                    "type": str(g.get("type") or ""),
                    "weight": _number(g.get("weight")),
                }
            )
    return graders


def case_set(result: Dict[str, Any]) -> Dict[str, Any]:
    """The case set as a dataset: names, folders, graders and a digest of the definitions.

    The digest covers each case's prompt and grader configuration, so it changes when a
    case changes; the prompt itself is never part of what is logged.
    """
    cases = sorted(result.get("cases") or [], key=lambda c: c["name"])
    definitions = [
        {
            "name": c["name"],
            "dir": _case_dir(c),
            "prompt": c.get("promptMarkdown") or "",
            "graders": c.get("graders") or [],
            "runsPerCase": c.get("runsPerCase"),
        }
        for c in cases
    ]
    canonical = json.dumps(
        definitions, sort_keys=True, separators=(",", ":"), default=str
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    names = [c["name"] for c in cases]
    return {
        "name": DATASET_NAME,
        "digest": digest,
        "source_type": "local",
        "source": json.dumps({"uri": "evals/"}),
        "schema": json.dumps(
            {
                "mlflow_colspec": [
                    {"type": "string", "name": "case", "required": True},
                    {"type": "string", "name": "dir", "required": True},
                    {"type": "long", "name": "runs_per_case", "required": False},
                    {"type": "string", "name": "graders", "required": False},
                ]
            }
        ),
        "profile": json.dumps({"num_rows": len(names), "cases": names}),
        "context": "eval",
    }


def _cases_table(result: Dict[str, Any], arms: List[str]) -> List[Dict[str, Any]]:
    """Per-case results by arm: names, counts and scores only, never a grader's explanation."""
    table = []
    for case in sorted(result.get("cases") or [], key=lambda c: c["name"]):
        aggregates = (
            case.get("aggregates") if isinstance(case.get("aggregates"), dict) else {}
        )
        table.append(
            {
                "case": case["name"],
                "dir": _case_dir(case),
                "runs_per_case": case.get("runsPerCase")
                if isinstance(case.get("runsPerCase"), int)
                else None,
                "graders": _grader_ids(case),
                "pass_rate": _number(aggregates.get("passRate")),
                "score": _number(aggregates.get("score")),
                "arms": {
                    arm: _arm_stats(_runs(case, arm))
                    for arm in arms
                    if _runs(case, arm)
                },
            }
        )
    return table


def git_commit(repo: Path = REPO) -> str:
    """The commit this logger runs from: git, else a release copy's REVISION file."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        for line in (repo / "REVISION").read_text(encoding="utf-8").splitlines():
            if line.startswith("sha="):
                return line[4:].strip() or "unknown"
    except OSError:
        pass
    return "unknown"


def build_plan(
    folder: Path,
    result: Dict[str, Any],
    elapsed_s: float,
    commit: str,
    user: str,
) -> Plan:
    suite = result.get("suite") or {}
    aggregates = result.get("aggregates") or {}
    cases = result.get("cases") or []
    arms = _arm_names(cases)

    errored = sum(
        1 for c in cases for arm in arms for r in _runs(c, arm) if r.get("error")
    )
    ok = 0.0 if result.get("partial") or errored else 1.0
    recorded = _number(result.get("durationSeconds"))

    metrics: Dict[str, float] = {
        "duration_s": recorded if recorded is not None else round(elapsed_s, 3),
        "ok": ok,
    }
    for key, source in (
        ("cases_total", "casesTotal"),
        ("cases_passed", "casesPassed"),
        ("overall_score", "overallScore"),
        ("overall_pass_rate", "overallPassRate"),
    ):
        value = _number(aggregates.get(source))
        if value is not None:
            metrics[key] = value
    cost = _number(result.get("costUsd"))
    if cost is not None:
        metrics["cost_usd"] = cost
    for arm in arms:
        runs = [r for c in cases for r in _runs(c, arm)]
        for key, value in _arm_stats(runs).items():
            metrics[f"{_metric_arm(arm)}.{key}"] = value

    plugins = [
        f"{p.get('name')}=={p.get('version')}"
        for p in suite.get("plugins") or []
        if isinstance(p, dict) and isinstance(p.get("name"), str)
    ]
    runs_per_case = sorted(
        {c["runsPerCase"] for c in cases if isinstance(c.get("runsPerCase"), int)}
    )
    candidates = {
        "model": suite.get("modelOverride") or suite.get("model"),
        "judge_model": suite.get("judgeModelOverride") or suite.get("judgeModel"),
        "ablation": suite.get("ablation"),
        "threshold": suite.get("threshold"),
        "concurrency": suite.get("concurrency"),
        "case_filter": suite.get("caseFilter"),
        "claude_version": result.get("claudeVersion"),
        "plugins": ", ".join(plugins) or None,
        "runs_per_case": ", ".join(str(n) for n in runs_per_case) or None,
        "arms": ", ".join(arms) or None,
        "started_at": result.get("startedAt"),
        "partial": str(bool(result.get("partial"))).lower(),
        "duration_from": "results" if recorded is not None else "logger",
    }
    params = {
        k: str(v)[:500]
        for k, v in candidates.items()
        if v is not None and not isinstance(v, (dict, list))
    }

    tags = {
        "homelab.project": PROJECT,
        "homelab.job.name": JOB,
        "mlflow.source.git.commit": commit,
        "mlflow.source.name": SOURCE_NAME,
        "mlflow.source.type": "LOCAL",
        "mlflow.user": user,
        RESULTS_TAG: folder.name,
    }
    return Plan(
        folder=folder.name,
        run_name=f"{JOB} {folder.name}",
        tags=tags,
        params=params,
        metrics=metrics,
        dataset=case_set(result),
        cases=_cases_table(result, arms),
    )


def _entities() -> Any:
    import mlflow.entities

    return mlflow.entities


def make_client() -> Any:
    from mlflow.tracking import MlflowClient

    return MlflowClient()


def ensure_experiment(client: Any) -> str:
    """The experiment's id, created with its tags if missing; missing tags are added."""
    experiment = client.get_experiment_by_name(EXPERIMENT)
    if experiment is None:
        return str(client.create_experiment(EXPERIMENT, tags=dict(EXPERIMENT_TAGS)))
    if getattr(experiment, "lifecycle_stage", "active") != "active":
        raise RuntimeError(
            f"experiment {EXPERIMENT} is deleted; restore it in MLflow first"
        )
    present = getattr(experiment, "tags", None) or {}
    for key, value in EXPERIMENT_TAGS.items():
        if key not in present:
            client.set_experiment_tag(experiment.experiment_id, key, value)
    return str(experiment.experiment_id)


def find_logged(client: Any, experiment_id: str, folder: str) -> Optional[str]:
    """The id of a finished run already logged for this results folder, if any."""
    runs = client.search_runs(
        [experiment_id],
        filter_string=f"tags.`{RESULTS_TAG}` = '{folder}' and attributes.status = 'FINISHED'",
        max_results=1,
    )
    return runs[0].info.run_id if runs else None


def write_run(client: Any, plan: Plan, entities: Any = None) -> Optional[str]:
    """Write the plan as one run; return its id, or None when the folder was logged before."""
    if not FOLDER_RE.match(plan.folder):
        raise ValueError(f"{plan.folder}: not a results folder name")
    ent = entities if entities is not None else _entities()
    experiment_id = ensure_experiment(client)
    if find_logged(client, experiment_id, plan.folder):
        return None
    now = int(time.time() * 1000)
    run = client.create_run(
        experiment_id, start_time=now, tags=plan.tags, run_name=plan.run_name
    )
    run_id = run.info.run_id
    try:
        client.log_batch(
            run_id,
            metrics=[ent.Metric(k, v, now, 0) for k, v in plan.metrics.items()],
            params=[ent.Param(k, v) for k, v in plan.params.items()],
        )
        d = plan.dataset
        dataset = ent.Dataset(
            name=d["name"],
            digest=d["digest"],
            source_type=d["source_type"],
            source=d["source"],
            schema=d["schema"],
            profile=d["profile"],
        )
        client.log_inputs(
            run_id,
            datasets=[
                ent.DatasetInput(
                    dataset=dataset,
                    tags=[ent.InputTag("mlflow.data.context", d["context"])],
                )
            ],
        )
        client.log_dict(
            run_id, {"folder": plan.folder, "cases": plan.cases}, CASES_ARTIFACT
        )
    except Exception:
        try:
            client.set_terminated(run_id, "FAILED")
        except Exception:
            pass
        raise
    client.set_terminated(run_id, "FINISHED")
    return str(run_id)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=f"Log one claude plugin eval results folder to the MLflow experiment {EXPERIMENT}."
    )
    parser.add_argument(
        "folder",
        nargs="?",
        help="a results folder (name or path); default: the newest in --results-dir",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=DEFAULT_RESULTS_DIR,
        help="where the results folders are (default: evals/results in this repository)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would be logged; contact nothing",
    )
    args = parser.parse_args(argv)
    started = time.time()

    try:
        folder = resolve_folder(args.folder, args.results_dir)
        result = load_result(folder)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    user = os.environ.get("MLFLOW_TRACKING_USERNAME") or DEFAULT_USER
    plan = build_plan(folder, result, time.time() - started, git_commit(), user)

    if args.dry_run:
        print(
            json.dumps(
                {
                    "experiment": EXPERIMENT,
                    "run_name": plan.run_name,
                    "tags": plan.tags,
                    "params": plan.params,
                    "metrics": plan.metrics,
                    "dataset": {
                        k: plan.dataset[k] for k in ("name", "digest", "profile")
                    },
                },
                indent=2,
            )
        )
        return 0

    if not os.environ.get("MLFLOW_TRACKING_URI"):
        print("error: MLFLOW_TRACKING_URI is not set", file=sys.stderr)
        return 2
    # A by-hand logger: fail in seconds rather than retrying for minutes.
    os.environ.setdefault("MLFLOW_HTTP_REQUEST_TIMEOUT", "10")
    os.environ.setdefault("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "2")

    try:
        run_id = write_run(make_client(), plan)
    except (
        Exception
    ) as exc:  # the logger's only job is logging: report and exit non-zero
        print(
            f"error: mlflow logging failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1
    if run_id is None:
        print(f"skip: {plan.folder} is already logged in {EXPERIMENT}")
    else:
        print(f"logged {plan.folder} to {EXPERIMENT} as run {run_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
