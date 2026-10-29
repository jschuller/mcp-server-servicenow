"""scripts/log_evals_to_mlflow.py: one results folder, one MLflow run, offline with a fake client."""

import copy
import dataclasses
import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "eval_results"
FOLDER = "2026-10-20T10-00-00-000Z"


def _load_script() -> Any:
    spec = importlib.util.spec_from_file_location(
        "log_evals_to_mlflow", ROOT / "scripts" / "log_evals_to_mlflow.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


logger = _load_script()


# --- fakes -------------------------------------------------------------------------------


@dataclasses.dataclass
class Metric:
    key: str
    value: float
    timestamp: int
    step: int


@dataclasses.dataclass
class Param:
    key: str
    value: str


@dataclasses.dataclass
class InputTag:
    key: str
    value: str


@dataclasses.dataclass
class Dataset:
    name: str
    digest: str
    source_type: str
    source: str
    schema: Optional[str] = None
    profile: Optional[str] = None


@dataclasses.dataclass
class DatasetInput:
    dataset: Dataset
    tags: List[InputTag]


ENTITIES = SimpleNamespace(
    Metric=Metric,
    Param=Param,
    InputTag=InputTag,
    Dataset=Dataset,
    DatasetInput=DatasetInput,
)
FILTER_RE = re.compile(
    r"^tags\.`evals\.results` = '([^']*)' and attributes\.status = 'FINISHED'$"
)


class FakeClient:
    """The MlflowClient calls the logger makes, recorded in memory."""

    def __init__(self, fail_on: Optional[str] = None) -> None:
        self.experiments: Dict[str, SimpleNamespace] = {}
        self.runs: List[Dict[str, Any]] = []
        self.filters: List[str] = []
        self.fail_on = fail_on

    def _maybe_fail(self, name: str) -> None:
        if self.fail_on == name:
            raise RuntimeError(f"{name} failed")

    def get_experiment_by_name(self, name: str) -> Optional[SimpleNamespace]:
        return self.experiments.get(name)

    def create_experiment(self, name: str, tags: Dict[str, str]) -> str:
        eid = str(len(self.experiments) + 1)
        self.experiments[name] = SimpleNamespace(
            experiment_id=eid, tags=dict(tags), lifecycle_stage="active"
        )
        return eid

    def set_experiment_tag(self, experiment_id: str, key: str, value: str) -> None:
        for exp in self.experiments.values():
            if exp.experiment_id == experiment_id:
                exp.tags[key] = value

    def search_runs(
        self, experiment_ids: List[str], filter_string: str, max_results: int
    ) -> List[SimpleNamespace]:
        self.filters.append(filter_string)
        match = FILTER_RE.match(filter_string)
        assert match, filter_string
        found = [
            SimpleNamespace(info=SimpleNamespace(run_id=r["id"]))
            for r in self.runs
            if r["experiment_id"] in experiment_ids
            and r["tags"].get("evals.results") == match.group(1)
            and r["status"] == "FINISHED"
        ]
        return found[:max_results]

    def create_run(
        self,
        experiment_id: str,
        start_time: int,
        tags: Dict[str, str],
        run_name: str,
    ) -> SimpleNamespace:
        run = {
            "id": f"run{len(self.runs) + 1}",
            "experiment_id": experiment_id,
            "start_time": start_time,
            "tags": dict(tags),
            "run_name": run_name,
            "status": "RUNNING",
            "metrics": {},
            "params": {},
            "inputs": [],
            "artifacts": {},
        }
        self.runs.append(run)
        return SimpleNamespace(info=SimpleNamespace(run_id=run["id"]))

    def _run(self, run_id: str) -> Dict[str, Any]:
        return next(r for r in self.runs if r["id"] == run_id)

    def log_batch(
        self, run_id: str, metrics: List[Metric], params: List[Param]
    ) -> None:
        self._maybe_fail("log_batch")
        self._run(run_id)["metrics"].update({m.key: m.value for m in metrics})
        self._run(run_id)["params"].update({p.key: p.value for p in params})

    def log_inputs(self, run_id: str, datasets: List[DatasetInput]) -> None:
        self._maybe_fail("log_inputs")
        self._run(run_id)["inputs"].extend(datasets)

    def log_dict(
        self, run_id: str, dictionary: Dict[str, Any], artifact_file: str
    ) -> None:
        self._run(run_id)["artifacts"][artifact_file] = dictionary

    def set_terminated(self, run_id: str, status: str) -> None:
        self._run(run_id)["status"] = status


# --- helpers -----------------------------------------------------------------------------


def _result() -> Dict[str, Any]:
    return json.loads((FIXTURES / FOLDER / "aggregate-result.json").read_text())


def _plan(result: Optional[Dict[str, Any]] = None, elapsed: float = 1.5) -> Any:
    return logger.build_plan(
        FIXTURES / FOLDER,
        result if result is not None else _result(),
        elapsed,
        "abc123",
        "homelab-service",
    )


def _write_folder(parent: Path, name: str, result: Dict[str, Any]) -> Path:
    folder = parent / name
    folder.mkdir(parents=True)
    (folder / "aggregate-result.json").write_text(json.dumps(result))
    return folder


# --- reading a results folder ------------------------------------------------------------


def test_newest_folder_is_the_last_timestamp_with_a_result(tmp_path: Path) -> None:
    _write_folder(tmp_path, "2026-10-12T00-14-10-601Z", _result())
    _write_folder(tmp_path, "2026-10-18T23-16-57-156Z", _result())
    (tmp_path / "2026-10-19T00-00-00-000Z").mkdir()  # an unfinished run: no result file
    (tmp_path / "notes.txt").write_text("x")
    assert logger.newest_folder(tmp_path).name == "2026-10-18T23-16-57-156Z"


def test_no_results_folder_is_an_input_error(tmp_path: Path) -> None:
    with pytest.raises(logger.InputError, match="no folder"):
        logger.newest_folder(tmp_path)
    with pytest.raises(logger.InputError, match="no such results directory"):
        logger.newest_folder(tmp_path / "missing")


def test_resolve_folder_takes_a_name_or_a_path() -> None:
    assert logger.resolve_folder(FOLDER, FIXTURES) == FIXTURES / FOLDER
    assert (
        logger.resolve_folder(str(FIXTURES / FOLDER), Path("/nonexistent"))
        == FIXTURES / FOLDER
    )
    assert logger.resolve_folder(None, FIXTURES) == FIXTURES / FOLDER


@pytest.mark.parametrize(
    "content, match",
    [
        ("not json", "cannot read"),
        (json.dumps({"schemaVersion": 2}), "schemaVersion 1"),
        (json.dumps({"schemaVersion": 1, "cases": [{"arms": {}}]}), "named cases"),
        (
            json.dumps(
                {"schemaVersion": 1, "cases": [{"name": "a", "arms": {"with": {}}}]}
            ),
            "named cases",
        ),
        (json.dumps({"schemaVersion": 1, "suite": []}), "suite"),
    ],
)
def test_load_result_refuses_what_is_not_an_eval_result(
    tmp_path: Path, content: str, match: str
) -> None:
    folder = tmp_path / FOLDER
    folder.mkdir()
    (folder / "aggregate-result.json").write_text(content)
    with pytest.raises(logger.InputError, match=match):
        logger.load_result(folder)


def test_load_result_refuses_a_folder_name_unfit_for_a_filter(tmp_path: Path) -> None:
    folder = _write_folder(tmp_path, "x' or '1'='1", _result())
    with pytest.raises(logger.InputError, match="not a results folder name"):
        logger.load_result(folder)


# --- the plan: tags, params, metrics, dataset --------------------------------------------


def test_run_name_and_tags_follow_the_standard() -> None:
    plan = _plan()
    assert plan.run_name == f"skill-evals {FOLDER}"
    assert plan.tags == {
        "homelab.project": "mcp-servicenow",
        "homelab.job.name": "skill-evals",
        "mlflow.source.git.commit": "abc123",
        "mlflow.source.name": "scripts/log_evals_to_mlflow.py",
        "mlflow.source.type": "LOCAL",
        "mlflow.user": "homelab-service",
        "evals.results": FOLDER,
    }


def test_metrics_aggregate_each_arm_and_the_suite() -> None:
    m = _plan().metrics
    assert m["duration_s"] == 42  # recorded by the eval run
    assert m["ok"] == 1
    assert m["cases_total"] == 2
    assert m["cases_passed"] == 1
    assert m["overall_score"] == 0.875
    assert m["overall_pass_rate"] == 0.5
    assert m["cost_usd"] == 0.5
    # with: 4 runs over both cases, 3 passed
    assert m["with.runs"] == 4
    assert m["with.runs_passed"] == 3
    assert m["with.runs_errored"] == 0
    assert m["with.pass_rate"] == 0.75
    assert m["with.score_mean"] == pytest.approx(0.875)
    assert m["with.turns_mean"] == 4
    assert m["with.cost_usd"] == pytest.approx(0.4)
    assert m["with.judge_cost_usd"] == pytest.approx(0.02)
    # without: only where-used has the arm
    assert m["without.runs"] == 2
    assert m["without.pass_rate"] == 0
    assert m["without.cost_usd"] == pytest.approx(0.1)
    # key names carry no case names, ids or thresholds
    assert not any("where-used" in k or "access-hygiene" in k for k in m)


def test_params_name_the_models_and_versions_never_a_path() -> None:
    p = _plan().params
    assert p["model"] == "sonnet"
    assert p["judge_model"] == "haiku"
    assert p["ablation"] == "none"
    assert p["claude_version"] == "2.1.303"
    assert p["plugins"] == "servicenow==0.9.3"
    assert p["arms"] == "with, without"
    assert p["runs_per_case"] == "2"
    assert p["started_at"] == "2026-10-20T10:00:00.000Z"
    assert p["partial"] == "false"
    assert p["duration_from"] == "results"
    assert all(isinstance(v, str) for v in p.values())


def test_the_case_set_is_a_dataset_of_names_and_a_digest() -> None:
    d = _plan().dataset
    assert d["name"] == "skill-eval-cases"
    assert re.fullmatch(r"[0-9a-f]{16}", d["digest"])
    assert d["context"] == "eval"
    assert json.loads(d["profile"]) == {
        "num_rows": 2,
        "cases": ["access-hygiene", "where-used"],
    }
    assert json.loads(d["source"]) == {"uri": "evals/"}
    assert json.loads(d["schema"])["mlflow_colspec"][0]["name"] == "case"


def test_digest_follows_the_case_definitions_not_their_order() -> None:
    result = _result()
    reordered = copy.deepcopy(result)
    reordered["cases"].reverse()
    assert _plan(reordered).dataset["digest"] == _plan(result).dataset["digest"]
    changed = copy.deepcopy(result)
    changed["cases"][0]["promptMarkdown"] += " (edited)"
    assert _plan(changed).dataset["digest"] != _plan(result).dataset["digest"]


def test_nothing_logged_carries_a_prompt_a_transcript_or_a_local_path() -> None:
    plan = _plan()
    logged = json.dumps(dataclasses.asdict(plan))
    for marker in (
        "PROMPT-TEXT",
        "EXPLANATION-NEVER-LOGGED",
        "/home/someone",
        "/tmp/fake-run",
        "trace.jsonl",
    ):
        assert marker not in logged
    dirs = {c["case"]: c["dir"] for c in plan.cases}
    assert dirs == {
        "where-used": "evals/where-used",
        "access-hygiene": "access-hygiene",
    }


def test_cases_table_has_per_case_arm_scores() -> None:
    cases = {c["case"]: c for c in _plan().cases}
    assert cases["where-used"]["arms"]["with"]["pass_rate"] == 0.5
    assert cases["where-used"]["arms"]["without"]["runs"] == 2
    assert "without" not in cases["access-hygiene"]["arms"]
    assert cases["where-used"]["graders"] == [
        {"name": "skill-fired", "type": "tool_used", "weight": 1.0},
        {"name": "names-callers", "type": "regex", "weight": 2.0},
    ]


@pytest.mark.parametrize("change", ["partial", "error"])
def test_ok_is_zero_for_a_partial_run_or_an_errored_case_run(change: str) -> None:
    result = _result()
    if change == "partial":
        result["partial"] = True
    else:
        result["cases"][1]["arms"]["with"][0]["error"] = "usage limit"
    m = _plan(result).metrics
    assert m["ok"] == 0
    if change == "error":
        assert m["with.runs_errored"] == 1


def test_duration_falls_back_to_the_loggers_own_time() -> None:
    result = _result()
    del result["durationSeconds"]
    plan = _plan(result, elapsed=2.25)
    assert plan.metrics["duration_s"] == 2.25
    assert plan.params["duration_from"] == "logger"


def test_git_commit_falls_back_to_a_release_revision_file(tmp_path: Path) -> None:
    (tmp_path / "REVISION").write_text("sha=0123abcd\nfrom=origin/main\n")
    assert logger.git_commit(tmp_path) == "0123abcd"
    (tmp_path / "REVISION").unlink()
    assert logger.git_commit(tmp_path) == "unknown"


# --- writing the run ---------------------------------------------------------------------


def test_write_run_creates_the_experiment_and_one_complete_run() -> None:
    client = FakeClient()
    plan = _plan()
    run_id = logger.write_run(client, plan, ENTITIES)
    assert run_id == "run1"

    exp = client.experiments["mcp-servicenow-evals"]
    assert exp.tags["homelab.project"] == "mcp-servicenow"
    assert exp.tags["homelab.kind"] == "evaluation"
    assert exp.tags["mlflow.experimentKind"] == "genai_development"
    assert "scripts/log_evals_to_mlflow.py" in exp.tags["mlflow.note.content"]

    (run,) = client.runs
    assert run["run_name"] == f"skill-evals {FOLDER}"
    assert run["tags"] == plan.tags
    assert run["status"] == "FINISHED"
    assert run["metrics"] == plan.metrics
    assert {"duration_s", "ok"} <= set(run["metrics"])
    assert run["params"] == plan.params
    (inp,) = run["inputs"]
    assert inp.dataset.name == "skill-eval-cases"
    assert inp.dataset.digest == plan.dataset["digest"]
    assert inp.dataset.source_type == "local"
    assert inp.tags == [InputTag("mlflow.data.context", "eval")]
    assert run["artifacts"]["evals/cases.json"]["folder"] == FOLDER
    assert len(run["artifacts"]["evals/cases.json"]["cases"]) == 2


def test_write_run_is_idempotent_per_results_folder() -> None:
    client = FakeClient()
    assert logger.write_run(client, _plan(), ENTITIES) == "run1"
    assert logger.write_run(client, _plan(), ENTITIES) is None
    assert len(client.runs) == 1
    assert client.filters[-1] == (
        f"tags.`evals.results` = '{FOLDER}' and attributes.status = 'FINISHED'"
    )
    # another folder is another run
    other = _plan()
    other.folder = "2026-10-21T10-00-00-000Z"
    other.tags = {**other.tags, "evals.results": other.folder}
    assert logger.write_run(client, other, ENTITIES) == "run2"


def test_an_existing_experiment_gets_only_its_missing_tags() -> None:
    client = FakeClient()
    client.experiments["mcp-servicenow-evals"] = SimpleNamespace(
        experiment_id="7",
        tags={"mlflow.note.content": "the owner's own description"},
        lifecycle_stage="active",
    )
    logger.write_run(client, _plan(), ENTITIES)
    tags = client.experiments["mcp-servicenow-evals"].tags
    assert tags["mlflow.note.content"] == "the owner's own description"
    assert tags["homelab.kind"] == "evaluation"
    assert client.runs[0]["experiment_id"] == "7"


def test_a_deleted_experiment_is_refused() -> None:
    client = FakeClient()
    client.experiments["mcp-servicenow-evals"] = SimpleNamespace(
        experiment_id="7", tags={}, lifecycle_stage="deleted"
    )
    with pytest.raises(RuntimeError, match="deleted"):
        logger.write_run(client, _plan(), ENTITIES)
    assert client.runs == []


def test_a_failed_write_marks_the_run_failed_and_a_retry_logs_it() -> None:
    client = FakeClient(fail_on="log_inputs")
    with pytest.raises(RuntimeError, match="log_inputs failed"):
        logger.write_run(client, _plan(), ENTITIES)
    assert client.runs[0]["status"] == "FAILED"
    client.fail_on = None
    assert logger.write_run(client, _plan(), ENTITIES) == "run2"
    assert client.runs[1]["status"] == "FINISHED"


# --- the command line --------------------------------------------------------------------


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://mlflow.invalid")
    monkeypatch.delenv("MLFLOW_TRACKING_USERNAME", raising=False)
    monkeypatch.setenv("MLFLOW_HTTP_REQUEST_TIMEOUT", "10")
    monkeypatch.setenv("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "2")
    monkeypatch.setattr(logger, "_entities", lambda: ENTITIES)
    return monkeypatch


def test_main_logs_the_newest_folder_then_skips_it(
    env: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    shutil.copytree(FIXTURES / FOLDER, tmp_path / FOLDER)
    client = FakeClient()
    env.setattr(logger, "make_client", lambda: client)
    assert logger.main(["--results-dir", str(tmp_path)]) == 0
    assert (
        f"logged {FOLDER} to mcp-servicenow-evals as run run1"
        in capsys.readouterr().out
    )
    assert client.runs[0]["tags"]["mlflow.user"] == "homelab-service"
    assert logger.main(["--results-dir", str(tmp_path)]) == 0
    assert "skip:" in capsys.readouterr().out
    assert len(client.runs) == 1


def test_main_dry_run_contacts_nothing(
    env: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    env.delenv("MLFLOW_TRACKING_URI")

    def no_client() -> None:
        raise AssertionError("a dry run must not build a client")

    env.setattr(logger, "make_client", no_client)
    assert logger.main([FOLDER, "--results-dir", str(FIXTURES), "--dry-run"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["run_name"] == f"skill-evals {FOLDER}"
    assert printed["metrics"]["ok"] == 1


def test_main_needs_a_tracking_uri(
    env: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    env.delenv("MLFLOW_TRACKING_URI")
    assert logger.main([FOLDER, "--results-dir", str(FIXTURES)]) == 2
    assert "MLFLOW_TRACKING_URI" in capsys.readouterr().err


def test_main_bad_input_exits_2(
    env: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert logger.main(["--results-dir", str(tmp_path)]) == 2
    assert "no folder" in capsys.readouterr().err


def test_main_mlflow_failure_exits_1(
    env: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    env.setattr(logger, "make_client", lambda: FakeClient(fail_on="log_batch"))
    assert logger.main([FOLDER, "--results-dir", str(FIXTURES)]) == 1
    assert "mlflow logging failed" in capsys.readouterr().err


def test_main_uses_the_tracking_username_as_the_user(
    env: pytest.MonkeyPatch,
) -> None:
    env.setenv("MLFLOW_TRACKING_USERNAME", "someone-else")
    client = FakeClient()
    env.setattr(logger, "make_client", lambda: client)
    assert logger.main([FOLDER, "--results-dir", str(FIXTURES)]) == 0
    assert client.runs[0]["tags"]["mlflow.user"] == "someone-else"
