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

``mcp-server-servicenow --eval-summary aggregate-result.json`` turns a finished run
(``schemaVersion`` 1) into a Markdown table for a ``RESULTS.md``, and with ``--badge FILE``
writes a shields.io endpoint badge. A partial run is refused.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
            data, _, _ = _frontmatter((skill / "SKILL.md").read_text(encoding="utf-8"))
            metadata = (data or {}).get("metadata") or {}
            value = metadata.get(TABLES_KEY) if isinstance(metadata, dict) else None
            if isinstance(value, str):
                tables.update(value.split())
    return sorted(tables)


def write_eval_mocks(plugin_dir: Path, version: str) -> List[Tuple[str, str]]:
    """Write the mock kit; return (``wrote`` or ``kept``, path relative to the plugin)."""
    manifest = read_manifest(plugin_dir)
    server = servicenow_server(manifest)
    if server is None:
        raise EvalKitError(
            f"{plugin_dir}: plugin.json has no mcpServers entry that runs "
            "mcp-server-servicenow"
        )
    mocks = plugin_dir / "evals" / "mocks" / server
    (mocks / "fixtures").mkdir(parents=True, exist_ok=True)
    done: List[Tuple[str, str]] = []

    def write(path: Path, text: str, overwrite: bool = False) -> None:
        rel = path.relative_to(plugin_dir).as_posix()
        if path.exists() and not overwrite:
            done.append(("kept", rel))
            return
        path.write_text(text, encoding="utf-8")
        done.append(("wrote", rel))

    write(
        mocks / "_tools.json",
        json.dumps(tools_list(version), indent=2) + "\n",
        overwrite=True,
    )
    for name, text in DEFAULT_MOCKS.items():
        write(mocks / name, text)
    for table in declared_tables(plugin_dir, manifest):
        write(mocks / "fixtures" / f"{table}.json", EMPTY_FIXTURE)
    return done


def _number(value: Any) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) else None


def _fmt(value: Optional[float], signed: bool = False) -> str:
    if value is None:
        return "—"
    return f"{value:+.2f}" if signed else f"{value:.2f}"


def _commit() -> Optional[str]:
    sha = os.environ.get("GITHUB_SHA")
    if sha:
        return sha[:12]
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


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


def summarize(result_path: Path) -> Tuple[str, Dict[str, Any]]:
    """Markdown for RESULTS.md and a shields.io endpoint badge, from a finished run."""
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EvalKitError(f"{result_path}: cannot read ({exc})") from exc
    if not isinstance(result, dict) or result.get("schemaVersion") != 1:
        raise EvalKitError(
            f"{result_path}: not a claude plugin eval result with schemaVersion 1"
        )
    if result.get("partial"):
        reason = result.get("partialReason") or "unknown reason"
        raise EvalKitError(
            f"{result_path}: a partial run ({reason}) is not comparable; "
            "run the suite to completion"
        )

    suite = result.get("suite") or {}
    agg = result.get("aggregates") or {}
    cases = [c for c in result.get("cases") or [] if isinstance(c, dict)]
    passed, total = agg.get("casesPassed"), agg.get("casesTotal")
    model = suite.get("modelOverride") or suite.get("model") or "default"
    judge = suite.get("judgeModelOverride") or suite.get("judgeModel") or "default"
    ablation = suite.get("ablation") or "default"
    runs = sorted(
        {c["runsPerCase"] for c in cases if isinstance(c.get("runsPerCase"), int)}
    )
    mean_delta = _number(agg.get("meanDelta"))
    threshold = _number(suite.get("threshold"))
    ci_url = _ci_run_url()
    commit = _commit()
    mocks_version = _mocks_version(result)

    rows = [
        (
            "Cases passed",
            f"{passed} / {total}"
            + (f" (threshold {threshold:g})" if threshold is not None else ""),
        ),
        ("Suite score", _fmt(_number(agg.get("overallScore")))),
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
        ("Cost (list-price estimate)", f"${_number(result.get('costUsd')) or 0:.2f}"),
        ("Started", str(result.get("startedAt") or "—")),
        ("Commit", commit or "—"),
        ("Kind", f"CI-run: {ci_url}" if ci_url else "self-reported"),
    ]
    lines = ["## Eval results", "", "| | |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in rows]
    lines += ["", "| Case | Score | Δ |", "|---|---|---|"]
    for case in cases:
        case_agg = case.get("aggregates") or {}
        lines.append(
            f"| {case.get('name', '?')} | {_fmt(_number(case_agg.get('score')))} | "
            f"{_fmt(_number(case_agg.get('delta')), signed=True)} |"
        )
    reproduce = f"claude plugin eval . --ablation {ablation}"
    if model != "default":
        reproduce += f" --model {model}"
    if judge != "default":
        reproduce += f" --judge-model {judge}"
    if runs:
        reproduce += f" --runs {runs[-1]}"
    lines += [
        "",
        "Δ compares the plugin with no plugin at all, and the mocked tools are absent "
        "without the plugin, so it overstates what the skills add over the bare tools.",
        "",
        f"Reproduce from this commit: `{reproduce}`",
        "",
    ]

    ratio = 0.0
    if isinstance(passed, int) and isinstance(total, int) and total > 0:
        ratio = passed / total
    color = "brightgreen" if ratio == 1 else ("yellow" if ratio >= 0.8 else "red")
    message = f"{passed}/{total} cases"
    if mean_delta is not None:
        message += f", Δ {mean_delta:+.2f}"
    badge = {"schemaVersion": 1, "label": "evals", "message": message, "color": color}
    return "\n".join(lines), badge
