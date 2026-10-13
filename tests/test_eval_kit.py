"""--eval-mocks and --eval-summary: the claude plugin eval kit, offline."""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

from servicenow_mcp.eval_kit import (
    TOOLS_META_KEY,
    EvalKitError,
    summarize,
    tools_list,
    write_eval_mocks,
    write_tools_only,
)
from servicenow_mcp.skill_lint import TABLES_KEY

MANIFEST = {
    "name": "my-skills",
    "skills": "./skills/",
    "mcpServers": {
        "servicenow": {
            "command": "uvx",
            "args": ["mcp-server-servicenow==0.9.0"],
            "env": {"SERVICENOW_INSTANCE_URL": "${SERVICENOW_INSTANCE_URL}"},
        }
    },
}
SKILL = f"""---
name: my-skill
description: x
metadata:
  {TABLES_KEY}: "task_sla contract_sla"
---

# My skill
"""


def make_plugin(root: Path, manifest: Dict[str, Any] = MANIFEST) -> Path:
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text(json.dumps(manifest))
    (root / "skills" / "my-skill").mkdir(parents=True)
    (root / "skills" / "my-skill" / "SKILL.md").write_text(SKILL)
    return root


RESULT: Dict[str, Any] = {
    "schemaVersion": 1,
    "claudeVersion": "2.1.296",
    "startedAt": "2026-10-12T00:14:10.601Z",
    "durationSeconds": 70,
    "costUsd": 0.2531643,
    "partial": False,
    "suite": {
        "root": "/Users/someone/private/path",
        "ablation": "with-without",
        "modelOverride": "sonnet",
        "threshold": 0.8,
    },
    "cases": [
        {
            "name": "sla-overlap",
            "runsPerCase": 3,
            "aggregates": {"score": 1, "delta": 0.5},
        },
        {"name": "change-collision", "runsPerCase": 3, "aggregates": {"score": 0.5}},
    ],
    "aggregates": {
        "casesTotal": 2,
        "casesPassed": 1,
        "overallScore": 0.75,
        "meanDelta": 0.25,
    },
}


def write_result(tmp_path: Path, result: Dict[str, Any]) -> Path:
    path = tmp_path / "aggregate-result.json"
    path.write_text(json.dumps(result))
    return path


@pytest.fixture(autouse=True)
def _not_in_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("GITHUB_ACTIONS", "GITHUB_SHA", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"):
        monkeypatch.delenv(var, raising=False)


def test_tools_list_is_the_wire_shape() -> None:
    listed = tools_list("9.9.9")
    names = [t["name"] for t in listed["tools"]]
    assert names == sorted(names) and "list_records" in names and len(names) == 19
    assert {"name", "description", "inputSchema"} <= set(listed["tools"][0])
    assert listed["_meta"] == {TOOLS_META_KEY: "9.9.9"}


def test_eval_mocks_writes_the_kit(tmp_path: Path) -> None:
    plugin = make_plugin(tmp_path)
    done = dict((path, action) for action, path in write_eval_mocks(plugin, "9.9.9"))
    base = "evals/mocks/servicenow/"
    assert done[base + "_tools.json"] == "wrote"
    for mock in (
        "list_records",
        "aggregate_records",
        "get_table_schema",
        "get_current_user",
    ):
        assert done[f"{base}{mock}.md"] == "wrote"
    for table in ("task_sla", "contract_sla"):
        fixture = plugin / base / "fixtures" / f"{table}.json"
        assert json.loads(fixture.read_text()) == {"count": 0, "records": []}
    aggregate = (plugin / base / "aggregate_records.md").read_text()
    assert "error: true" in aggregate and "Authentication failed (401)" in aggregate


def test_eval_mocks_keeps_edits_and_refreshes_tools(tmp_path: Path) -> None:
    plugin = make_plugin(tmp_path)
    write_eval_mocks(plugin, "9.9.8")
    mine = plugin / "evals/mocks/servicenow/list_records.md"
    mine.write_text("my own mock")
    done = dict((path, action) for action, path in write_eval_mocks(plugin, "9.9.9"))
    assert mine.read_text() == "my own mock"
    assert done["evals/mocks/servicenow/list_records.md"] == "kept"
    tools = json.loads((plugin / "evals/mocks/servicenow/_tools.json").read_text())
    assert tools["_meta"][TOOLS_META_KEY] == "9.9.9"


def test_eval_mocks_uses_the_plugins_server_name(tmp_path: Path) -> None:
    manifest = {
        **MANIFEST,
        "mcpServers": {"snow": MANIFEST["mcpServers"]["servicenow"]},
    }
    plugin = make_plugin(tmp_path, manifest)
    write_eval_mocks(plugin, "9.9.9")
    assert (plugin / "evals/mocks/snow/_tools.json").is_file()


@pytest.mark.parametrize(
    ("manifest", "expected"),
    [
        (None, "no .claude-plugin/plugin.json"),
        (
            {"name": "x", "mcpServers": {"other": {"command": "npx", "args": ["x"]}}},
            "runs",
        ),
    ],
)
def test_eval_mocks_errors(tmp_path: Path, manifest: Any, expected: str) -> None:
    if manifest is not None:
        make_plugin(tmp_path, manifest)
    with pytest.raises(EvalKitError, match=expected):
        write_eval_mocks(tmp_path, "9.9.9")


def test_summary_table_and_badge(tmp_path: Path) -> None:
    text, badge = summarize(write_result(tmp_path, RESULT))
    assert "| Cases passed | 1 / 2 (threshold 0.8) |" in text
    assert "| Δ vs no plugin | +0.25 |" in text
    assert "| Model / judge | sonnet / default |" in text
    assert "| sla-overlap | 1.00 | — | — | +0.50 |" in text
    assert "| change-collision | 0.50 | — | — | — |" in text
    assert "| Kind | self-reported |" in text
    assert (
        "claude plugin eval . --ablation with-without --model sonnet --runs 3" in text
    )
    assert "/Users/someone" not in text  # the author's paths stay private
    assert badge == {
        "schemaVersion": 1,
        "label": "evals",
        "message": "1/2 cases, Δ +0.25",
        "color": "red",
    }


def test_summary_in_ci_links_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REPOSITORY", "someone/skills")
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    monkeypatch.setenv("GITHUB_SHA", "0123456789abcdef")
    text, _ = summarize(write_result(tmp_path, RESULT))
    assert (
        "| Kind | CI-run: https://github.com/someone/skills/actions/runs/42 |" in text
    )
    assert "| Commit | 0123456789ab |" in text


def test_summary_reads_the_mocks_version(tmp_path: Path) -> None:
    plugin = make_plugin(tmp_path / "plugin")
    write_eval_mocks(plugin, "9.9.9")
    result = {**RESULT, "suite": {**RESULT["suite"], "root": str(plugin)}}
    text, _ = summarize(write_result(tmp_path, result))
    assert "| Mocks from | mcp-server-servicenow 9.9.9 |" in text


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"partial": True, "partialReason": "cost_ceiling"}, "partial run"),
        ({"schemaVersion": 2}, "schemaVersion 1"),
    ],
)
def test_summary_refuses(tmp_path: Path, change: Dict[str, Any], expected: str) -> None:
    with pytest.raises(EvalKitError, match=expected):
        summarize(write_result(tmp_path, {**RESULT, **change}))


def test_cli(tmp_path: Path) -> None:
    plugin = make_plugin(tmp_path / "plugin")
    cmd = [sys.executable, "-m", "servicenow_mcp.cli"]
    env = {**os.environ, "SERVICENOW_INSTANCE_URL": ""}
    env.pop("GITHUB_ACTIONS", None)
    out = subprocess.run(
        [*cmd, "--eval-mocks", str(plugin)], capture_output=True, text=True, env=env
    )
    assert out.returncode == 0, out.stdout + out.stderr
    assert "wrote   evals/mocks/servicenow/_tools.json" in out.stdout
    badge = tmp_path / "badge.json"
    out = subprocess.run(
        [
            *cmd,
            "--eval-summary",
            str(write_result(tmp_path, RESULT)),
            "--badge",
            str(badge),
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert out.returncode == 0 and "## Eval results" in out.stdout
    assert json.loads(badge.read_text())["label"] == "evals"
    partial = write_result(tmp_path, {**RESULT, "partial": True})
    out = subprocess.run(
        [*cmd, "--eval-summary", str(partial)], capture_output=True, text=True, env=env
    )
    assert out.returncode == 1 and "partial run" in out.stderr


def _case(name: str, runs: List[Dict[str, bool]], delta: Any = None) -> Dict[str, Any]:
    """A case whose 'task' grader passes per run as given; 'skill-fired' always passes."""
    return {
        "name": name,
        "runsPerCase": len(runs),
        "graders": [
            {"name": "task", "type": "llm"},
            {"name": "skill-fired", "type": "tool_used", "config": {"tool": "Skill"}},
        ],
        "arms": {
            "with": [
                {
                    "graders": [
                        {"name": "task", "passed": r["task"], "weight": 1},
                        {
                            "name": "skill-fired",
                            "passed": r.get("skill", False),
                            "weight": 1,
                        },
                    ]
                }
                for r in runs
            ]
        },
        "aggregates": {"score": 1, "delta": delta},
    }


def test_summary_against_a_tools_only_baseline(tmp_path: Path) -> None:
    with_skills = {
        **RESULT,
        "cases": [
            _case("fallback", [{"task": True, "skill": True}] * 2),
            _case("easy", [{"task": True, "skill": True}] * 2),
        ],
    }
    tools_only = {
        **RESULT,
        "costUsd": 0.5,
        "cases": [
            _case("fallback", [{"task": False}, {"task": False}]),
            _case("easy", [{"task": True}, {"task": True}]),
        ],
    }
    main = write_result(tmp_path, with_skills)
    base = tmp_path / "baseline.json"
    base.write_text(json.dumps(tools_only))
    text, badge = summarize(main, base)
    assert "| Δ vs tools only | +0.50 |" in text
    assert "| fallback | 1.00 | 0.00 | +1.00 |" in text
    assert "| easy | 1.00 | 1.00 | +0.00 |" in text
    assert "| Cost (list-price estimate) | $0.75 |" in text
    assert badge["message"] == "1/2 cases, +0.50 vs tools"
    assert (
        "--eval-baseline . ../tools-only && claude plugin eval ../tools-only --ablation none"
        in text
    )


def test_summary_refuses_a_baseline_with_other_models(tmp_path: Path) -> None:
    other = {**RESULT, "suite": {**RESULT["suite"], "modelOverride": "haiku"}}
    base = tmp_path / "baseline.json"
    base.write_text(json.dumps(other))
    with pytest.raises(EvalKitError, match="model haiku"):
        summarize(write_result(tmp_path, RESULT), base)


def test_summary_refuses_a_baseline_with_other_runs(tmp_path: Path) -> None:
    with_skills = {**RESULT, "cases": [_case("fallback", [{"task": True}] * 3)]}
    tools_only = {**RESULT, "cases": [_case("fallback", [{"task": False}])]}
    base = tmp_path / "baseline.json"
    base.write_text(json.dumps(tools_only))
    with pytest.raises(EvalKitError, match="baseline ran 1 run.*this run 3"):
        summarize(write_result(tmp_path, with_skills), base)


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"suite": "x"}, "suite is not an object"),
        ({"aggregates": [1]}, "aggregates is not an object"),
        ({"cases": {"a": 1}}, "cases is not a list"),
        ({"cases": ["a"]}, r"cases\[0\] is not an object"),
        ({"cases": [{"name": "a", "aggregates": 1}]}, r"cases\[0\].aggregates"),
        ({"cases": [{"name": "a", "graders": 5}]}, r"cases\[0\].graders is not a list"),
        ({"cases": [{"name": "a", "arms": {"with": 5}}]}, r"arms.with is not a list"),
        ({"cases": [{"name": "a", "arms": {"with": [1]}}]}, r"arms.with\[0\]"),
        (
            {"cases": [{"name": "a", "arms": {"with": [{"graders": "x"}]}}]},
            r"arms.with\[0\] is not a run",
        ),
    ],
)
def test_summary_refuses_a_malformed_result(
    tmp_path: Path, change: Dict[str, Any], expected: str
) -> None:
    with pytest.raises(EvalKitError, match=expected):
        summarize(write_result(tmp_path, {**RESULT, **change}))
    base = tmp_path / "baseline.json"
    base.write_text(json.dumps({**RESULT, **change}))
    with pytest.raises(EvalKitError, match=expected):
        summarize(write_result(tmp_path, RESULT), base)


def test_summary_notes_cases_missing_from_the_baseline(tmp_path: Path) -> None:
    with_skills = {
        **RESULT,
        "cases": [
            _case("fallback", [{"task": True}]),
            _case("new-case", [{"task": True}]),
        ],
    }
    tools_only = {**RESULT, "cases": [_case("fallback", [{"task": False}])]}
    base = tmp_path / "baseline.json"
    base.write_text(json.dumps(tools_only))
    text, _ = summarize(write_result(tmp_path, with_skills), base)
    assert "| Δ vs tools only | +1.00 (1 of 2 cases) |" in text
    assert "Not in the tools-only baseline: new-case." in text
    _, badge = summarize(write_result(tmp_path, with_skills), base)
    assert badge["message"].endswith("+1.00 vs tools (1/2)")
    base.write_text(json.dumps({**RESULT, "cases": [_case("other", [{"task": True}])]}))
    with pytest.raises(EvalKitError, match="no case names in common"):
        summarize(write_result(tmp_path, with_skills), base)


def test_summary_refuses_runs_that_errored(tmp_path: Path) -> None:
    case = _case("fallback", [{"task": True}])
    case["arms"]["with"][0]["error"] = "usage limit reached"
    with pytest.raises(EvalKitError, match="ended with an error"):
        summarize(write_result(tmp_path, {**RESULT, "cases": [case]}))


def test_task_score_weights_and_unscored_graders(tmp_path: Path) -> None:
    case = _case("c", [{"task": True}])
    run = case["arms"]["with"][0]["graders"]
    run.append({"name": "advisory", "passed": False, "weight": 0})
    run.append({"name": "not-scored", "passed": False, "weight": 1, "scored": False})
    run.append("not a grader")
    base = tmp_path / "baseline.json"
    base.write_text(json.dumps({**RESULT, "cases": [_case("c", [{"task": True}])]}))
    text, _ = summarize(write_result(tmp_path, {**RESULT, "cases": [case]}), base)
    assert "| c | 1.00 | 1.00 | +0.00 |" in text


def test_summary_marks_uncommitted_changes(tmp_path: Path) -> None:
    plugin = make_plugin(tmp_path / "plugin")
    git = [
        "git",
        "-C",
        str(plugin),
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.com",
    ]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-qm", "init"], check=True)
    result = {**RESULT, "suite": {**RESULT["suite"], "root": str(plugin)}}
    (plugin / "RESULTS.md").write_text("being written")
    text, _ = summarize(write_result(tmp_path, result))
    assert "(with uncommitted changes)" not in text
    replay = plugin / "evals" / "mocks" / "servicenow" / ".replay"
    replay.mkdir(parents=True)
    (replay / "a.json").write_text("{}")  # a run's new recordings
    text, _ = summarize(write_result(tmp_path, result))
    assert "(with uncommitted changes)" not in text
    (plugin / "skills" / "my-skill" / "SKILL.md").write_text(SKILL + "\nEdited\n")
    text, _ = summarize(write_result(tmp_path, result))
    assert "(with uncommitted changes)" in text


def test_cli_refuses_flags_without_their_mode(tmp_path: Path) -> None:
    cmd = [sys.executable, "-m", "servicenow_mcp.cli"]
    env = {**os.environ, "SERVICENOW_INSTANCE_URL": ""}
    for args, expected in (
        (["--badge", "b.json"], "--badge works only with --eval-summary"),
        (["--strict"], "--strict works only with --validate-skills"),
        (["--eval-mocks", "x", "--eval-summary", "y"], "can't be combined"),
    ):
        out = subprocess.run([*cmd, *args], capture_output=True, text=True, env=env)
        assert out.returncode == 2 and expected in out.stderr, out.stderr
    out = subprocess.run([*cmd, "--version"], capture_output=True, text=True, env=env)
    assert out.returncode == 0 and out.stdout.startswith("mcp-server-servicenow ")


def test_tools_only_copy(tmp_path: Path) -> None:
    plugin = make_plugin(tmp_path / "plugin")
    write_eval_mocks(plugin, "9.9.9")
    (plugin / "evals" / "results" / "old").mkdir(parents=True)
    (plugin / "evals" / "case").mkdir()
    (plugin / "evals" / "case" / "prompt.md").write_text("Hi")
    out = tmp_path / "tools-only"
    write_tools_only(plugin, out)
    manifest = json.loads((out / ".claude-plugin" / "plugin.json").read_text())
    assert "skills" not in manifest and manifest["name"] == "my-skills"
    assert (out / "evals" / "case" / "prompt.md").is_file()
    assert (out / "evals" / "mocks" / "servicenow" / "_tools.json").is_file()
    assert not (out / "evals" / "results").exists() and not (out / "skills").exists()
    # A second run replaces its own earlier copy, so the baseline can't go stale ...
    (plugin / "evals" / "case" / "prompt.md").write_text("Changed")
    write_tools_only(plugin, out)
    assert (out / "evals" / "case" / "prompt.md").read_text() == "Changed"
    # ... but never a folder it didn't write.
    other = tmp_path / "other"
    other.mkdir()
    (other / "keep.txt").write_text("mine")
    with pytest.raises(EvalKitError, match="not an earlier --eval-baseline copy"):
        write_tools_only(plugin, other)
    assert (other / "keep.txt").read_text() == "mine"


@pytest.mark.parametrize(
    ("out", "expected"),
    [("plugin/evals/base", "outside the plugin"), ("plugin", "outside")],
)
def test_tools_only_copy_refuses_folders_in_the_plugin(
    tmp_path: Path, out: str, expected: str
) -> None:
    plugin = make_plugin(tmp_path / "plugin")
    (plugin / "evals").mkdir()
    with pytest.raises(EvalKitError, match=expected):
        write_tools_only(plugin, tmp_path / out)


def test_tools_only_copy_refuses_links_and_files(tmp_path: Path) -> None:
    plugin = make_plugin(tmp_path / "plugin")
    (plugin / "evals").mkdir()
    (tmp_path / "secret.txt").write_text("x")
    (plugin / "evals" / "link.md").symlink_to(tmp_path / "secret.txt")
    with pytest.raises(EvalKitError, match="symlink"):
        write_tools_only(plugin, tmp_path / "out")
    (plugin / "evals" / "link.md").unlink()
    (tmp_path / "file").write_text("x")
    with pytest.raises(EvalKitError, match="is a file"):
        write_tools_only(plugin, tmp_path / "file")
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / ".eval-baseline").write_text("")
    (tmp_path / "linked").symlink_to(tmp_path / "real")
    with pytest.raises(EvalKitError, match="is a symlink"):
        write_tools_only(plugin, tmp_path / "linked")
    with pytest.raises(EvalKitError, match="contains the plugin"):
        write_tools_only(plugin, tmp_path)


def test_eval_mocks_refuse_paths_outside_the_plugin(tmp_path: Path) -> None:
    skill = SKILL.replace(
        '"task_sla contract_sla"', '"task_sla ../../../../escaped /tmp/absolute"'
    )
    plugin = make_plugin(tmp_path / "plugin")
    (plugin / "skills" / "my-skill" / "SKILL.md").write_text(skill)
    done = write_eval_mocks(plugin, "9.9.9")
    assert any(action == "skipped" and "escaped" in path for action, path in done)
    assert any(action == "skipped" and "absolute" in path for action, path in done)
    assert not list(tmp_path.rglob("escaped.json"))
    manifest = {
        **MANIFEST,
        "mcpServers": {"../x": MANIFEST["mcpServers"]["servicenow"]},
    }
    (plugin / ".claude-plugin" / "plugin.json").write_text(json.dumps(manifest))
    with pytest.raises(EvalKitError, match="not a plain name"):
        write_eval_mocks(plugin, "9.9.9")
