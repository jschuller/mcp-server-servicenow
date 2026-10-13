"""Tools for testing skills with ``claude plugin eval``: mocks of this server, and run summaries.

``mcp-server-servicenow --eval-mocks PLUGIN_DIR`` writes ``evals/mocks/<server>/`` for a
Claude Code plugin whose ``mcpServers`` runs this server:

- ``_tools.json``: this version's ``tools/list``, rewritten on every run so mocked tools
  carry the real names, descriptions and input schemas;
- default mocks modelled on the start-here identity (``itil`` + ``snc_read_only`` over an
  API key): ``list_records`` answers from ``fixtures/<table>.json``, the Aggregate API is
  refused with a 401 and the schema with a 403, in the words this server uses;
- an empty fixture for every table the plugin's skills declare.

Existing mocks and fixtures are kept, so edit them freely.

``mcp-server-servicenow --eval-baseline PLUGIN_DIR OUT_DIR`` copies the plugin without its
skills, so the same cases run against the bare tools. OUT_DIR must be outside the plugin; a
later run replaces a folder an earlier run wrote, and no other.

``mcp-server-servicenow --eval-summary aggregate-result.json [--baseline tools-only.json]``
turns a finished run (``schemaVersion`` 1) into a Markdown table for a ``RESULTS.md``, with
what the skills add over the bare tools when a baseline run is given; ``--badge FILE``
writes a shields.io endpoint badge. A partial run, a run with failed runs (a usage limit
scores 0) and a baseline made with other models are refused.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from servicenow_mcp import __version__
from servicenow_mcp.middleware.policy import IDENTIFIER_RE
from servicenow_mcp.skill_lint import (
    TABLES_KEY,
    _frontmatter,
    find_skill_dirs,
    registered_tools,
    servicenow_server,
)

TOOLS_META_KEY = "io.github.jschuller/server-version"
INSTANCE = "https://example.service-now.com"

LIST_RECORDS_MOCK = """---
expect:
  table_name: /^[A-Za-z0-9_]+$/
---

{{file:fixtures/{input.table_name}.json}}
"""

AGGREGATE_REFUSED_MOCK = (
    "---\nerror: true\n---\n\n"
    "Authentication failed (401). Check the API key and that a REST API access policy "
    "maps it for this API and method (GET). "
    f"URL: {INSTANCE}/api/now/stats/{{{{input.table_name}}}} | "
    'Response: {"error":{"message":"User is not authenticated",'
    '"detail":"Required to provide Auth information"},"status":"failure"}\n'
)

SCHEMA_REFUSED_MOCK = (
    "---\nerror: true\n---\n\n"
    "Access denied (403). The user may lack permissions for this API; roles per tool: "
    "https://github.com/jschuller/mcp-server-servicenow/blob/main/docs/tools.md#roles. "
    f"URL: {INSTANCE}/api/now/table/sys_dictionary | "
    'Response: {"error":{"message":"Insufficient rights to query records",'
    '"detail":"Field(s) present in the query do not have permission to be read"},'
    '"status":"failure"}\n'
)

CURRENT_USER_MOCK = (
    json.dumps(
        {
            "user_name": "svc.reader",
            "user_display_name": "Read-only integration",
            "user_email": "",
            "user_sys_id": "0a1b2c3d4e5f60718293a4b5c6d7e8f9",
            "roles": ["itil", "snc_read_only"],
        }
    )
    + "\n"
)

DEFAULT_MOCKS = {
    "list_records.md": LIST_RECORDS_MOCK,
    "aggregate_records.md": AGGREGATE_REFUSED_MOCK,
    "get_table_schema.md": SCHEMA_REFUSED_MOCK,
    "get_current_user.md": CURRENT_USER_MOCK,
}
EMPTY_FIXTURE = '{"count": 0, "records": []}\n'
SERVER_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
# Marks a folder --eval-baseline wrote, so a later run may replace it.
BASELINE_MARKER = ".eval-baseline"


class EvalKitError(Exception):
    """A problem the command reports on one line and exits 1 for."""


def tools_list(version: str) -> Dict[str, Any]:
    """This server's tools/list response, as ``_tools.json`` stores it."""
    tools = [
        tool.to_mcp_tool().model_dump(mode="json", by_alias=True, exclude_none=True)
        for tool in asyncio.run(registered_tools())
    ]
    tools.sort(key=lambda t: t["name"])
    return {"tools": tools, "_meta": {TOOLS_META_KEY: version}}


def read_manifest(plugin_dir: Path) -> Dict[str, Any]:
    path = plugin_dir / ".claude-plugin" / "plugin.json"
    if not path.is_file():
        raise EvalKitError(f"{plugin_dir}: no .claude-plugin/plugin.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EvalKitError(f"{path}: not valid JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise EvalKitError(f"{path}: must be a JSON object")
    return data


def skill_paths(plugin_dir: Path, manifest: Dict[str, Any]) -> List[Path]:
    declared = manifest.get("skills", "./skills/")
    entries = declared if isinstance(declared, list) else [declared]
    return [plugin_dir / e for e in entries if isinstance(e, str)]


def declared_tables(plugin_dir: Path, manifest: Dict[str, Any]) -> List[str]:
    """Every table the plugin's skills declare in their metadata."""
    tables = set()
    for root in skill_paths(plugin_dir, manifest):
        if not root.exists():
            continue
        for skill in find_skill_dirs(root):
            try:
                text = (skill / "SKILL.md").read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                raise EvalKitError(
                    f"{skill / 'SKILL.md'}: cannot read ({exc})"
                ) from exc
            data, _, _ = _frontmatter(text)
            metadata = (data or {}).get("metadata") or {}
            value = metadata.get(TABLES_KEY) if isinstance(metadata, dict) else None
            if isinstance(value, str):
                tables.update(value.split())
    return sorted(tables)


def _inside(path: Path, root: Path) -> bool:
    """True when ``path`` resolves inside ``root``, symlinks followed."""
    return path.resolve().is_relative_to(root.resolve())


def write_eval_mocks(plugin_dir: Path, version: str) -> List[Tuple[str, str]]:
    """Write the mock kit; return (``wrote``, ``kept`` or ``skipped``, relative path)."""
    manifest = read_manifest(plugin_dir)
    server = servicenow_server(manifest)
    if server is None:
        raise EvalKitError(
            f"{plugin_dir}: plugin.json has no mcpServers entry that runs "
            "mcp-server-servicenow"
        )
    if not SERVER_NAME_RE.match(server):
        raise EvalKitError(
            f"{plugin_dir}: mcpServers name {server!r} is not a plain name "
            "(letters, digits, - and _)"
        )
    mocks = plugin_dir / "evals" / "mocks" / server
    if not _inside(mocks, plugin_dir):
        raise EvalKitError(f"{mocks}: resolves outside the plugin folder")
    try:
        (mocks / "fixtures").mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise EvalKitError(f"{mocks}: cannot create ({exc})") from exc
    if not _inside(mocks / "fixtures", plugin_dir):
        raise EvalKitError(f"{mocks / 'fixtures'}: resolves outside the plugin folder")
    done: List[Tuple[str, str]] = []

    def write(path: Path, text: str, overwrite: bool = False) -> None:
        rel = path.relative_to(plugin_dir).as_posix()
        if path.is_symlink():
            raise EvalKitError(f"{rel}: is a symlink; replace it with a file")
        if path.exists() and not overwrite:
            done.append(("kept", rel))
            return
        try:
            path.write_text(text, encoding="utf-8")
        except OSError as exc:
            raise EvalKitError(f"{rel}: cannot write ({exc})") from exc
        done.append(("wrote", rel))

    write(
        mocks / "_tools.json",
        json.dumps(tools_list(version), indent=2) + "\n",
        overwrite=True,
    )
    for name, text in DEFAULT_MOCKS.items():
        write(mocks / name, text)
    fixtures = (mocks / "fixtures").relative_to(plugin_dir).as_posix()
    for table in declared_tables(plugin_dir, manifest):
        if not IDENTIFIER_RE.match(table):
            done.append(("skipped", f"{fixtures}/ (not a table name: {table!r})"))
            continue
        fixture = mocks / "fixtures" / f"{table}.json"
        write(fixture, EMPTY_FIXTURE)
    return done


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _fmt(value: Optional[float], signed: bool = False) -> str:
    if value is None:
        return "—"
    return f"{value:+.2f}" if signed else f"{value:.2f}"


def _git(root: Path, *args: str) -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def _commit(result: Dict[str, Any]) -> Optional[str]:
    """The commit the suite ran from, marked when its skills or evals had uncommitted edits."""
    root_value = (result.get("suite") or {}).get("root")
    root = Path(root_value) if isinstance(root_value, str) else None
    if root is None or not root.is_dir():
        sha = os.environ.get("GITHUB_SHA")
        return sha[:12] if sha else None
    sha = os.environ.get("GITHUB_SHA", "")[:12] or _git(
        root, "rev-parse", "--short=12", "HEAD"
    )
    if not sha:
        return None
    # Edits to what was evaluated, not to RESULTS.md or the badge being written now.
    dirty = _git(
        root,
        "status",
        "--porcelain",
        "--",
        "skills",
        "evals",
        ".claude-plugin",
        ":(exclude)evals/badge.json",
        ":(exclude)evals/mocks/*/.replay/",  # recordings a run may add
    )
    return f"{sha} (with uncommitted changes)" if dirty else sha


def _ci_run_url() -> Optional[str]:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return None
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo, run = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_RUN_ID")
    return f"{server}/{repo}/actions/runs/{run}" if repo and run else None


def _mocks_version(result: Dict[str, Any]) -> Optional[str]:
    """The server version that generated the suite's ``_tools.json``, when it can be found."""
    root = (result.get("suite") or {}).get("root")
    if not isinstance(root, str):
        return None
    for path in sorted(Path(root).glob("evals/mocks/*/_tools.json")):
        try:
            meta = json.loads(path.read_text(encoding="utf-8")).get("_meta") or {}
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(meta, dict) and isinstance(meta.get(TOOLS_META_KEY), str):
            return str(meta[TOOLS_META_KEY])
    return None


def write_tools_only(plugin_dir: Path, out_dir: Path) -> List[str]:
    """Copy a plugin without its skills, so the same cases measure the bare tools.

    The copy keeps the manifest's name, so mocked tool names match the graders, and the
    whole ``evals/`` folder except ``results/``. Return the paths written.
    """
    manifest = read_manifest(plugin_dir)
    if servicenow_server(manifest) is None:
        raise EvalKitError(
            f"{plugin_dir}: plugin.json has no mcpServers entry that runs "
            "mcp-server-servicenow"
        )
    if out_dir.is_symlink():
        raise EvalKitError(f"{out_dir}: is a symlink; give a real folder")
    plugin, out = plugin_dir.resolve(), out_dir.resolve()
    if out == plugin or out.is_relative_to(plugin):
        raise EvalKitError(
            f"{out_dir}: give a folder outside the plugin, e.g. ../tools-only"
        )
    if plugin.is_relative_to(out):
        raise EvalKitError(
            f"{out_dir}: contains the plugin; give a new folder, e.g. ../tools-only"
        )
    if out_dir.exists() and not out_dir.is_dir():
        raise EvalKitError(f"{out_dir}: is a file; give a folder")
    evals = plugin_dir / "evals"
    if not evals.is_dir() or evals.is_symlink():
        raise EvalKitError(f"{plugin_dir}: no evals/ folder to copy")
    for dirpath, dirnames, filenames in os.walk(evals):
        dirnames[:] = [d for d in dirnames if d != "results"]
        for name in dirnames + filenames:
            if (Path(dirpath) / name).is_symlink():
                rel = (Path(dirpath) / name).relative_to(plugin_dir).as_posix()
                raise EvalKitError(f"{rel}: is a symlink; the copy takes files only")
    if out_dir.exists() and any(out_dir.iterdir()):
        if not (out_dir / BASELINE_MARKER).is_file():
            raise EvalKitError(
                f"{out_dir}: not empty, and not an earlier --eval-baseline copy; "
                "give a new folder"
            )
        shutil.rmtree(out_dir)  # an earlier copy: replace it, so it can't go stale
    baseline = {k: v for k, v in manifest.items() if k != "skills"}
    baseline["description"] = "Tools-only baseline: the same server, no skills"
    try:
        (out_dir / ".claude-plugin").mkdir(parents=True)
        (out_dir / BASELINE_MARKER).write_text(
            "Written by mcp-server-servicenow --eval-baseline; the next run replaces "
            "this folder.\n",
            encoding="utf-8",
        )
        (out_dir / ".claude-plugin" / "plugin.json").write_text(
            json.dumps(baseline, indent=2) + "\n", encoding="utf-8"
        )
        shutil.copytree(
            evals,
            out_dir / "evals",
            ignore=lambda folder, names: [n for n in names if n == "results"],
        )
    except (OSError, shutil.Error) as exc:
        raise EvalKitError(f"{out_dir}: copy failed ({exc})") from exc
    return [".claude-plugin/plugin.json", "evals/"]


def _load_result(path: Path) -> Dict[str, Any]:
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EvalKitError(f"{path}: cannot read ({exc})") from exc
    if not isinstance(result, dict) or result.get("schemaVersion") != 1:
        raise EvalKitError(
            f"{path}: not a claude plugin eval result with schemaVersion 1"
        )
    malformed = _malformed(result)
    if malformed:
        raise EvalKitError(f"{path}: not a claude plugin eval result ({malformed})")
    if result.get("partial"):
        reason = result.get("partialReason") or "unknown reason"
        raise EvalKitError(
            f"{path}: a partial run ({reason}) is not comparable; "
            "run the suite to completion"
        )
    return result


def _malformed(result: Dict[str, Any]) -> Optional[str]:
    """The first field this summary reads that lacks the shape ``claude plugin eval`` writes."""
    for key in ("suite", "aggregates"):
        if not isinstance(result.get(key) or {}, dict):
            return f"{key} is not an object"
    suite = result.get("suite") or {}
    for key in ("model", "modelOverride", "judgeModel", "judgeModelOverride", "root"):
        value = suite.get(key)
        if value is not None and (not isinstance(value, str) or "\0" in value):
            return f"suite.{key} is not a string"
    cases = result.get("cases") or []
    if not isinstance(cases, list):
        return "cases is not a list"
    for i, case in enumerate(cases):
        where = f"cases[{i}]"
        if not isinstance(case, dict):
            return f"{where} is not an object"
        for key, kind in (("aggregates", dict), ("arms", dict), ("graders", list)):
            if not isinstance(case.get(key) or kind(), kind):
                return (
                    f"{where}.{key} is not {'an object' if kind is dict else 'a list'}"
                )
        graders = [(f"{where}.graders", case.get("graders") or [])]
        for arm, runs in (case.get("arms") or {}).items():
            if not isinstance(runs or [], list):
                return f"{where}.arms.{arm} is not a list"
            for j, run in enumerate(runs or []):
                if not isinstance(run, dict) or not isinstance(
                    run.get("graders") or [], list
                ):
                    return f"{where}.arms.{arm}[{j}] is not a run with a graders list"
                graders.append(
                    (f"{where}.arms.{arm}[{j}].graders", run.get("graders") or [])
                )
        named = [(where, case)] + [
            (f"{at}[{k}]", g) for at, gs in graders for k, g in enumerate(gs)
        ]
        for at, item in named:
            name = item.get("name") if isinstance(item, dict) else None
            if name is not None and not isinstance(name, str):
                return f"{at}.name is not a string"
    return None


def _skill_graders(case: Dict[str, Any]) -> Set[Any]:
    """Graders that check the Skill tool fired: they can't pass without skills."""
    names = set()
    for grader in case.get("graders") or []:
        if not isinstance(grader, dict):
            continue
        config = grader.get("config") or {}
        if (
            grader.get("type") == "tool_used"
            and isinstance(config, dict)
            and config.get("tool") == "Skill"
        ):
            names.add(grader.get("name"))
    return names


def _with_runs(case: Dict[str, Any]) -> List[Dict[str, Any]]:
    arms = case.get("arms")
    runs = arms.get("with") if isinstance(arms, dict) else None
    return [r for r in runs or [] if isinstance(r, dict)]


def _weight(grader: Dict[str, Any]) -> float:
    weight = _number(grader.get("weight"))
    return 1.0 if weight is None else weight


def _task_score(case: Dict[str, Any]) -> Optional[float]:
    """Mean with-arm score over the scored graders that aren't Skill checks."""
    skip = _skill_graders(case)
    scores = []
    for run in _with_runs(case):
        graders = [
            g
            for g in run.get("graders") or []
            if isinstance(g, dict)
            and g.get("name") not in skip
            and g.get("scored") is not False
        ]
        weight = sum(_weight(g) for g in graders)
        if weight > 0:
            got = sum(_weight(g) for g in graders if g.get("passed") is True)
            scores.append(got / weight)
    return sum(scores) / len(scores) if scores else None


def _runs_per_case(result: Dict[str, Any]) -> List[int]:
    """Runs that finished per case, which --runs can make fewer than the suite's runsPerCase."""
    cases = [c for c in result.get("cases") or [] if isinstance(c, dict)]
    return sorted({len(_with_runs(c)) for c in cases if _with_runs(c)}) or sorted(
        {c["runsPerCase"] for c in cases if isinstance(c.get("runsPerCase"), int)}
    )


def _failed_runs(result: Dict[str, Any]) -> List[str]:
    """Runs that ended in an error (a usage limit, a timeout): their score is not the skill's."""
    failed = []
    for case in result.get("cases") or []:
        if not isinstance(case, dict):
            continue
        arms = case.get("arms")
        for arm, runs in (arms if isinstance(arms, dict) else {}).items():
            for run in runs or []:
                if isinstance(run, dict) and run.get("error"):
                    failed.append(f"{case.get('name', '?')} ({arm})")
    return failed


def _check_baseline(
    result: Dict[str, Any], baseline: Dict[str, Any], path: Path
) -> None:
    """Refuse a tools-only run made with other models or another number of runs."""
    mine, theirs = result.get("suite") or {}, baseline.get("suite") or {}
    for label, keys in (
        ("model", ("modelOverride", "model")),
        ("judge model", ("judgeModelOverride", "judgeModel")),
    ):
        a = next((mine.get(k) for k in keys if mine.get(k)), None)
        b = next((theirs.get(k) for k in keys if theirs.get(k)), None)
        if a != b:
            raise EvalKitError(
                f"{path}: the baseline ran with {label} {b or 'default'}, this run with "
                f"{a or 'default'}; run both with the same --model and --judge-model"
            )
    finished = {
        c.get("name"): len(_with_runs(c))
        for c in baseline.get("cases") or []
        if isinstance(c, dict)
    }
    for case in result.get("cases") or []:
        if not isinstance(case, dict) or case.get("name") not in finished:
            continue
        mine, theirs = len(_with_runs(case)), finished[case.get("name")]
        if mine != theirs:
            raise EvalKitError(
                f"{path}: case {case.get('name')} has {theirs} finished run(s) in the "
                f"baseline and {mine} in this run; run both with the same --runs"
            )


def summarize(
    result_path: Path, baseline_path: Optional[Path] = None
) -> Tuple[str, Dict[str, Any]]:
    """Markdown for RESULTS.md and a shields.io endpoint badge, from a finished run.

    With ``baseline_path`` (a tools-only run of the same cases, from ``--eval-baseline``),
    it also reports what the skills add over the bare tools, case by case.
    """
    result = _load_result(result_path)
    baseline = _load_result(baseline_path) if baseline_path else None
    for path, run in ((result_path, result), (baseline_path, baseline)):
        failed = _failed_runs(run) if run is not None else []
        if failed:
            raise EvalKitError(
                f"{path}: {len(failed)} run(s) ended with an error, e.g. {failed[0]} "
                "(a usage limit or a timeout scores 0); run the suite again"
            )
    if baseline is not None and baseline_path is not None:
        _check_baseline(result, baseline, baseline_path)

    suite = result.get("suite") or {}
    agg = result.get("aggregates") or {}
    cases = [c for c in result.get("cases") or [] if isinstance(c, dict)]
    passed, total = agg.get("casesPassed"), agg.get("casesTotal")
    model = suite.get("modelOverride") or suite.get("model") or "default"
    judge = suite.get("judgeModelOverride") or suite.get("judgeModel") or "default"
    ablation = suite.get("ablation") or "default"
    runs = _runs_per_case(result)
    mean_delta = _number(agg.get("meanDelta"))
    threshold = _number(suite.get("threshold"))
    ci_url = _ci_run_url()
    commit = _commit(result)
    mocks_version = _mocks_version(result)

    tools_only: Dict[Any, Optional[float]] = {}
    unmatched: List[str] = []
    if baseline is not None:
        tools_only = {
            c.get("name"): _task_score(c)
            for c in baseline.get("cases") or []
            if isinstance(c, dict)
        }
        unmatched = [
            str(c.get("name")) for c in cases if c.get("name") not in tools_only
        ]
        if len(unmatched) == len(cases):
            raise EvalKitError(
                f"{baseline_path}: no case names in common with this run; "
                "make the baseline with --eval-baseline from the same plugin"
            )
    over_tools = [
        s - t
        for c in cases
        for s, t in [(_task_score(c), tools_only.get(c.get("name")))]
        if s is not None and t is not None
    ]
    mean_over_tools = sum(over_tools) / len(over_tools) if over_tools else None
    if mean_over_tools is not None and len(over_tools) < len(cases):
        over_tools_text = (
            f"{mean_over_tools:+.2f} ({len(over_tools)} of {len(cases)} cases)"
        )
    elif mean_over_tools is not None:
        over_tools_text = f"{mean_over_tools:+.2f}"
    else:
        over_tools_text = "— (no tools-only baseline)"

    rows = [
        (
            "Cases passed",
            (
                f"{passed} / {total}"
                if isinstance(passed, int) and isinstance(total, int)
                else "—"
            )
            + (f" (threshold {threshold:g})" if threshold is not None else ""),
        ),
        ("Suite score", _fmt(_number(agg.get("overallScore")))),
        ("Δ vs tools only", over_tools_text),
        (
            "Δ vs no plugin",
            _fmt(mean_delta, signed=True)
            if mean_delta is not None
            else f"— (ablation {ablation})",
        ),
        ("Model / judge", f"{model} / {judge}"),
        ("Runs per case", ", ".join(str(r) for r in runs) or "—"),
        ("Claude Code", str(result.get("claudeVersion") or "—")),
        (
            "Mocks from",
            f"mcp-server-servicenow {mocks_version}" if mocks_version else "—",
        ),
        ("Cost (list-price estimate)", f"${_cost(result, baseline):.2f}"),
        ("Started", str(result.get("startedAt") or "—")),
        ("Commit", commit or "—"),
        ("Kind", f"CI-run: {ci_url}" if ci_url else "self-reported"),
    ]
    lines = ["## Eval results", "", "| | |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in rows]
    lines += [
        "",
        "| Case | Score | Tools only | Δ vs tools | Δ vs no plugin |",
        "|---|---|---|---|---|",
    ]
    for case in cases:
        case_agg = case.get("aggregates") or {}
        mine, bare = _task_score(case), tools_only.get(case.get("name"))
        lines.append(
            f"| {case.get('name', '?')} | {_fmt(_number(case_agg.get('score')))} | "
            f"{_fmt(bare)} | "
            f"{_fmt(mine - bare if mine is not None and bare is not None else None, signed=True)} | "
            f"{_fmt(_number(case_agg.get('delta')), signed=True)} |"
        )
    reproduce = f"claude plugin eval . --ablation {ablation}"
    if model != "default":
        reproduce += f" --model {shlex.quote(model)}"
    if judge != "default":
        reproduce += f" --judge-model {shlex.quote(judge)}"
    if runs:
        reproduce += f" --runs {runs[-1]}"
    if threshold is not None:
        reproduce += f" --threshold {threshold:g}"
    lines += [
        "",
        "- **Δ vs tools only:** the same cases with this server's tools and no skills "
        "(`--eval-baseline`), scored without the graders that check a skill fired. "
        "It is what the skills add.",
        "- **Δ vs no plugin:** what `claude plugin eval` reports. The mocked tools are "
        "absent without the plugin, so it overstates what the skills add.",
        "- **Score** is `claude plugin eval`'s case score, which counts the graders that "
        "check a skill fired; **Tools only** and **Δ vs tools** leave those graders out.",
        "",
        f"Reproduce from this commit: `{reproduce}`",
        "",
    ]
    if unmatched:
        lines[-1:-1] = [
            "",
            f"Not in the tools-only baseline: {', '.join(unmatched)}.",
        ]
    if baseline is not None:
        baseline_cmd = (
            f"uvx mcp-server-servicenow=={__version__} --eval-baseline . ../tools-only && "
            + reproduce.replace("eval .", "eval ../tools-only").replace(
                f"--ablation {ablation}", "--ablation none"
            )
        )
        lines[-1:-1] = ["", f"Tools-only baseline: `{baseline_cmd}`"]

    ratio = 0.0
    if isinstance(passed, int) and isinstance(total, int) and total > 0:
        ratio = passed / total
    color = "brightgreen" if ratio == 1 else ("yellow" if ratio >= 0.8 else "red")
    message = (
        f"{passed}/{total} cases"
        if isinstance(passed, int) and isinstance(total, int)
        else "no cases"
    )
    if mean_over_tools is not None:
        message += f", {mean_over_tools:+.2f} vs tools"
        if len(over_tools) < len(cases):
            message += f" ({len(over_tools)}/{len(cases)})"
    elif mean_delta is not None:
        message += f", Δ {mean_delta:+.2f}"
    badge = {"schemaVersion": 1, "label": "evals", "message": message, "color": color}
    return "\n".join(lines), badge


def _cost(result: Dict[str, Any], baseline: Optional[Dict[str, Any]]) -> float:
    total = _number(result.get("costUsd")) or 0.0
    if baseline is not None:
        total += _number(baseline.get("costUsd")) or 0.0
    return total
