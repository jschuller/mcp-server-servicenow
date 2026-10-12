"""Validate ServiceNow skills: plain Agent Skills plus this server's profile.

``mcp-server-servicenow --validate-skills PATH [PATH ...]`` runs these checks offline,
for this repository's own skills and for skills other people write in their own
repositories. A path is one skill folder (it holds a ``SKILL.md``) or any folder
above skills; every ``SKILL.md`` below it is checked, skipping hidden folders.

The profile (docs/skill-profile.md) adds to the Agent Skills specification:

- ``metadata`` keys ``io.github.jschuller/servicenow-roles`` and
  ``io.github.jschuller/servicenow-tables`` (space-separated) declare the roles a
  skill needs and every table it reads, and ``io.github.jschuller/servicenow-writes``
  names the write tools it calls;
- tool calls live in fenced code blocks, written as calls
  (``list_records(table_name="incident", query="...")``), and must pass the same
  identifier and ``javascript:`` rules the server applies at run time;
- files are text only (``.md``, ``.txt``, ``.csv``), with no symlinks, within the
  SEP-2640 per-skill limits, and relative links stay inside the skill.

A folder holding ``.claude-plugin/plugin.json`` is checked as a plugin wrapper too: it may
declare only skills and one ``mcpServers`` entry that runs ``uvx mcp-server-servicenow``,
because ``claude plugin eval`` runs a plugin's hooks, agents and servers as the person
evaluating it. Its ``evals/mocks/<server>/_tools.json`` must match this server's tools.

Errors make a skill unusable or unsafe; warnings are things a reviewer should look
at (undeclared write-tool calls, links outside ServiceNow's documentation,
credential-like text).
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple

import yaml

from servicenow_mcp.middleware.policy import (
    FIELD_LIST_ARGS,
    FIELD_LIST_RE,
    FIXED_TABLES,
    IDENTIFIER_RE,
    ORDER_BY_RE,
    QUERY_ARGS,
    find_unsafe_js,
)

ROLES_KEY = "io.github.jschuller/servicenow-roles"
TABLES_KEY = "io.github.jschuller/servicenow-tables"
WRITES_KEY = "io.github.jschuller/servicenow-writes"

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
ROLE_RE = re.compile(r"^[A-Za-z0-9_.]+$")
ALLOWED_SUFFIXES = {".md", ".txt", ".csv"}
MAX_FILES = 512  # SEP-2640: resources per skill, SKILL.md included
MAX_BYTES = 16 * 1024 * 1024  # SEP-2640: total size per skill
MAX_NAME = 64
MAX_DESCRIPTION = 1024

DOC_URL_RE = re.compile(
    r"^https://(www\.servicenow\.com/docs/|github\.com/ServiceNow/ServiceNowDocs/)"
)
LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
FENCE_RE = re.compile(r"^(\s*)(`{3,}|~{3,})(.*)$")
CALL_NAME_RE = re.compile(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\s*\(")
CREDENTIAL_RES = (
    re.compile(
        r"(?i)\b(password|passwd|client_secret|secret|api[_-]?key|token)\b\s*[:=]\s*"
        r"(?!<)[\"']?[^\s\"'<>]{6,}"
    ),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{20,}"),
    re.compile(r"(?<![A-Za-z0-9+/=_-])[A-Za-z0-9+/_-]{40,}={0,2}(?![A-Za-z0-9+/=_-])"),
)
URL_RE = re.compile(r"https?://\S+")

PACKAGE_RE = re.compile(r"^mcp-server-servicenow(==\d+\.\d+\.\d+)?$")
PLUGIN_METADATA_KEYS = {
    "$schema",
    "name",
    "version",
    "description",
    "author",
    "homepage",
    "repository",
    "license",
    "keywords",
}
# Manifest keys and default locations that add hooks, agents, commands or other code.
PLUGIN_CODE_KEYS = {
    "hooks",
    "agents",
    "commands",
    "monitors",
    "lspServers",
    "outputStyles",
    "mods",
    "settings",
}
PLUGIN_CODE_PATHS = (
    "hooks",
    "agents",
    "commands",
    "monitors",
    "output-styles",
    "bin",
    ".mcp.json",
    ".lsp.json",
    "settings.json",
)
SECRET_ENV_RE = re.compile(r"(?i)(password|secret|api_?key|token)")
ENV_REF_RE = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*(:-[^}]*)?\}$")


@dataclass
class Finding:
    level: str  # "error" or "warning"
    path: str  # relative to the skill folder
    line: Optional[int]
    message: str

    def render(self) -> str:
        where = self.path + (f":{self.line}" if self.line else "")
        return f"  {self.level:<7} {where}  {self.message}"


@dataclass
class SkillReport:
    name: str
    path: Path
    digest: str = ""
    writes: List[str] = field(default_factory=list)  # declared write tools
    findings: List[Finding] = field(default_factory=list)

    def add(self, level: str, path: str, line: Optional[int], message: str) -> None:
        self.findings.append(Finding(level, path, line, message))

    @property
    def errors(self) -> List[Finding]:
        return [f for f in self.findings if f.level == "error"]

    @property
    def warnings(self) -> List[Finding]:
        return [f for f in self.findings if f.level == "warning"]


@dataclass
class LintReport:
    skills: List[SkillReport] = field(default_factory=list)
    plugins: List[SkillReport] = field(default_factory=list)  # plugin wrappers
    problems: List[str] = field(default_factory=list)  # e.g. a path with no skills

    @property
    def error_count(self) -> int:
        return len(self.problems) + sum(len(s.errors) for s in self.checked)

    @property
    def warning_count(self) -> int:
        return sum(len(s.warnings) for s in self.checked)

    @property
    def checked(self) -> List[SkillReport]:
        return self.skills + self.plugins


@dataclass(frozen=True)
class ToolCatalog:
    """The server's tool names and which of them write."""

    read: frozenset[str]
    write: frozenset[str]

    @property
    def all(self) -> frozenset[str]:
        return self.read | self.write


async def registered_tools() -> List[Any]:
    """This server's tools, read offline (no instance, no configuration)."""
    from servicenow_mcp.server import mcp
    from servicenow_mcp.tools import (  # noqa: F401 — registers the tools
        cmdb_tools,
        system_tools,
        table_tools,
        update_set_tools,
    )

    return list(await mcp.list_tools())


def tool_catalog() -> ToolCatalog:
    """Read the registered tools offline (no instance, no configuration)."""
    tools = asyncio.run(registered_tools())
    read: Set[str] = set()
    write: Set[str] = set()
    for tool in tools:
        hint = getattr(tool.annotations, "read_only_hint", None)
        (read if hint else write).add(tool.name)
    return ToolCatalog(frozenset(read), frozenset(write))


def core_skill_names() -> Set[str]:
    root = Path(str(files("servicenow_mcp").joinpath("skills")))
    return {p.name for p in root.iterdir() if (p / "SKILL.md").is_file()}


def find_skill_dirs(root: Path) -> List[Path]:
    """Every folder at or below ``root`` that holds a SKILL.md (hidden folders skipped)."""
    if (root / "SKILL.md").is_file():
        return [root]
    found: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        if "SKILL.md" in filenames:
            found.append(Path(dirpath))
            dirnames[:] = []  # a skill's own subfolders belong to it
    return found


def _skill_files(skill: Path, report: SkillReport) -> List[Path]:
    """Walk one skill, reporting files the profile does not allow."""
    kept: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(skill, followlinks=False):
        here = Path(dirpath)
        for d in list(dirnames):
            sub = here / d
            rel = sub.relative_to(skill).as_posix()
            if sub.is_symlink():
                report.add("error", rel, None, "symlinks are not allowed")
                dirnames.remove(d)
            elif d.startswith("."):
                report.add("error", rel, None, "hidden folders are not allowed")
                dirnames.remove(d)
            elif (sub / "SKILL.md").is_file():
                dirnames.remove(d)  # a nested skill is checked on its own
        for name in sorted(filenames):
            path = here / name
            rel = path.relative_to(skill).as_posix()
            if path.is_symlink():
                report.add("error", rel, None, "symlinks are not allowed")
            elif name.startswith("."):
                report.add("error", rel, None, "hidden files are not allowed")
            elif path.suffix.lower() not in ALLOWED_SUFFIXES:
                report.add(
                    "error",
                    rel,
                    None,
                    "only .md, .txt and .csv files are allowed (no scripts or binaries)",
                )
            else:
                kept.append(path)
    return sorted(kept)


def _digest(skill: Path, paths: Iterable[Path]) -> str:
    h = hashlib.sha256()
    for path in sorted(paths, key=lambda p: p.relative_to(skill).as_posix()):
        file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        h.update(f"{path.relative_to(skill).as_posix()}\0{file_hash}\n".encode())
    return "sha256:" + h.hexdigest()


def _frontmatter(text: str) -> Tuple[Optional[dict], int, str]:
    """Return (frontmatter or None, the body's first line number, error)."""
    if not text.startswith("---"):
        return None, 1, "SKILL.md must start with YAML frontmatter (---)"
    lines = text.splitlines()
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            try:
                data = yaml.safe_load("\n".join(lines[1:i])) or {}
            except yaml.YAMLError as exc:
                return None, i + 2, f"frontmatter is not valid YAML: {exc}"
            if not isinstance(data, dict):
                return None, i + 2, "frontmatter must be a mapping"
            return data, i + 2, ""
    return None, 1, "frontmatter has no closing ---"


def _split_words(value: object) -> Optional[List[str]]:
    return value.split() if isinstance(value, str) else None


def _check_frontmatter(
    skill: Path,
    data: dict,
    report: SkillReport,
    core_names: Set[str],
    is_core: bool,
    catalog: ToolCatalog,
) -> Tuple[Optional[Set[str]], Set[str]]:
    """Check name/description/license/metadata; return (declared tables, declared writes)."""
    name = data.get("name")
    if not isinstance(name, str) or not name:
        report.add("error", "SKILL.md", None, "frontmatter needs a name")
    else:
        if len(name) > MAX_NAME or not NAME_RE.match(name):
            report.add(
                "error",
                "SKILL.md",
                None,
                f"name {name!r}: 1-64 lowercase letters, digits and single hyphens",
            )
        if name != skill.name:
            report.add(
                "error",
                "SKILL.md",
                None,
                f"name {name!r} must equal the folder name {skill.name!r}",
            )
        if name in core_names and not is_core:
            report.add(
                "warning",
                "SKILL.md",
                None,
                f"name {name!r} is also a skill this server ships; hosts may confuse them",
            )
    description = data.get("description")
    if not isinstance(description, str) or not description.strip():
        report.add("error", "SKILL.md", None, "frontmatter needs a description")
    elif len(description) > MAX_DESCRIPTION:
        report.add(
            "error",
            "SKILL.md",
            None,
            f"description is {len(description)} characters (at most {MAX_DESCRIPTION})",
        )
    if "license" not in data:
        report.add("warning", "SKILL.md", None, "no license: say how others may use it")

    metadata = data.get("metadata") or {}
    if not isinstance(metadata, dict):
        report.add("error", "SKILL.md", None, "metadata must be a mapping")
        return None, set()
    tables: Optional[Set[str]] = None
    writes: Set[str] = set()
    if TABLES_KEY in metadata:
        words = _split_words(metadata[TABLES_KEY])
        if words is None:
            report.add("error", "SKILL.md", None, f"{TABLES_KEY} must be a string")
        else:
            bad = [w for w in words if not IDENTIFIER_RE.match(w)]
            if bad:
                report.add(
                    "error",
                    "SKILL.md",
                    None,
                    f"{TABLES_KEY}: invalid table names {bad}",
                )
            tables = set(words)
    if ROLES_KEY in metadata:
        words = _split_words(metadata[ROLES_KEY])
        if words is None:
            report.add("error", "SKILL.md", None, f"{ROLES_KEY} must be a string")
        else:
            bad = [w for w in words if not ROLE_RE.match(w)]
            if bad:
                report.add(
                    "error", "SKILL.md", None, f"{ROLES_KEY}: invalid role names {bad}"
                )
    if WRITES_KEY in metadata:
        words = _split_words(metadata[WRITES_KEY])
        if words is None:
            report.add("error", "SKILL.md", None, f"{WRITES_KEY} must be a string")
        else:
            bad = [w for w in words if w not in catalog.write]
            if bad:
                report.add(
                    "error",
                    "SKILL.md",
                    None,
                    f"{WRITES_KEY}: not write tools of this server {bad}",
                )
            writes = set(words) - set(bad)
    return tables, writes


def _fences(text: str) -> Iterator[Tuple[int, str]]:
    """Yield (first content line number, content) for each fenced code block."""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = FENCE_RE.match(lines[i])
        if not m:
            i += 1
            continue
        marker = m.group(2)
        start = i + 1
        j = start
        while j < len(lines) and not lines[j].strip().startswith(marker):
            j += 1
        yield start + 1, "\n".join(line.strip() for line in lines[start:j])
        i = j + 1


def _outside_fences(text: str) -> List[Tuple[int, str]]:
    """(line number, line) for every line outside fenced code blocks."""
    out: List[Tuple[int, str]] = []
    fence: Optional[str] = None
    for n, line in enumerate(text.splitlines(), 1):
        m = FENCE_RE.match(line)
        if fence is None and m:
            fence = m.group(2)
            continue
        if fence is not None:
            if line.strip().startswith(fence):
                fence = None
            continue
        out.append((n, line))
    return out


def _is_placeholder(value: str) -> bool:
    return "<" in value and ">" in value


def _literal_kwargs(call: ast.Call) -> Dict[str, str]:
    return {
        kw.arg: kw.value.value
        for kw in call.keywords
        if kw.arg
        and isinstance(kw.value, ast.Constant)
        and isinstance(kw.value.value, str)
    }


def _check_calls(
    rel: str,
    first_line: int,
    content: str,
    catalog: ToolCatalog,
    tables: Optional[Set[str]],
    writes: Set[str],
    used: Set[str],
    report: SkillReport,
) -> None:
    names = set(CALL_NAME_RE.findall(content))
    if not names & catalog.all:
        return
    try:
        tree = ast.parse(content)
    except SyntaxError:
        report.add(
            "warning",
            rel,
            first_line,
            "a code block names a tool but is not a parseable call, so it was not checked",
        )
        return
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        tool = node.func.id
        line = first_line + node.lineno - 1
        if tool not in catalog.all:
            if "_" in tool:
                report.add(
                    "warning", rel, line, f"{tool}() is not a tool of this server"
                )
            continue
        if tool in catalog.write:
            used.add(tool)
            if tool not in writes:
                report.add(
                    "warning",
                    rel,
                    line,
                    f"{tool}() writes to the instance: declare it in {WRITES_KEY},"
                    " and say in the skill to ask before writing",
                )
        args = _literal_kwargs(node)
        table = args.get("table_name") or FIXED_TABLES.get(tool)
        if tool in ("list_ci", "get_ci", "create_ci", "update_ci"):
            table = args.get("class_name", "cmdb_ci")
        if table and not _is_placeholder(table):
            if not IDENTIFIER_RE.match(table):
                report.add(
                    "error", rel, line, f"{tool}(): invalid table name {table!r}"
                )
            else:
                used.add(table)
                declared = tables or set()
                cmdb_class = table.startswith("cmdb_ci") and "cmdb_ci" in declared
                if tables is None:
                    report.add(
                        "error",
                        rel,
                        line,
                        f"{tool}() reads {table}: declare the tables in {TABLES_KEY}",
                    )
                elif table not in declared and not cmdb_class:
                    report.add(
                        "error",
                        rel,
                        line,
                        f"{tool}() reads {table}, which {TABLES_KEY} does not declare",
                    )
        for key in FIELD_LIST_ARGS:
            value = args.get(key)
            if value and not _is_placeholder(value) and not FIELD_LIST_RE.match(value):
                report.add("error", rel, line, f"{tool}(): invalid {key} {value!r}")
        order_by = args.get("order_by")
        if (
            order_by
            and not _is_placeholder(order_by)
            and not ORDER_BY_RE.match(order_by)
        ):
            report.add("error", rel, line, f"{tool}(): invalid order_by {order_by!r}")
        for key in QUERY_ARGS:
            value = args.get(key)
            if value:
                unsafe = find_unsafe_js(value)
                if unsafe:
                    report.add(
                        "error",
                        rel,
                        line,
                        f"{tool}(): {key} has script the server refuses: {unsafe!r}",
                    )


def _check_text(skill: Path, path: Path, text: str, report: SkillReport) -> None:
    rel = path.relative_to(skill).as_posix()
    skill_root = skill.resolve()
    for n, line in _outside_fences(text):
        for target in LINK_RE.findall(line):
            if target.startswith("#"):
                continue
            if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
                if not DOC_URL_RE.match(target):
                    report.add(
                        "warning",
                        rel,
                        n,
                        f"link outside ServiceNow's documentation: {target[:80]}",
                    )
                continue
            local = target.split("#", 1)[0]
            if not local:
                continue
            resolved = (path.parent / local).resolve()
            if not resolved.is_relative_to(skill_root):
                report.add("error", rel, n, f"link leaves the skill folder: {target}")
            elif not resolved.exists():
                report.add("error", rel, n, f"link target does not exist: {target}")
    for n, line in enumerate(text.splitlines(), 1):
        stripped = URL_RE.sub("", line)
        if any(rx.search(stripped) for rx in CREDENTIAL_RES):
            report.add(
                "warning",
                rel,
                n,
                "looks like a credential or token; never put secrets in a skill",
            )


def lint_skill(
    skill: Path,
    catalog: ToolCatalog,
    core_names: Set[str],
    core_root: Optional[Path] = None,
) -> SkillReport:
    report = SkillReport(name=skill.name, path=skill)
    paths = _skill_files(skill, report)
    total = sum(p.stat().st_size for p in paths)
    if len(paths) > MAX_FILES:
        report.add("error", ".", None, f"{len(paths)} files (at most {MAX_FILES})")
    if total > MAX_BYTES:
        report.add("error", ".", None, f"{total} bytes (at most {MAX_BYTES})")
    report.digest = _digest(skill, paths)

    is_core = core_root is not None and skill.resolve().parent == core_root
    texts: Dict[Path, str] = {}
    for path in paths:
        try:
            texts[path] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            report.add(
                "error", path.relative_to(skill).as_posix(), None, "not UTF-8 text"
            )

    main = skill / "SKILL.md"
    data, body_line, problem = _frontmatter(texts.get(main, ""))
    tables: Optional[Set[str]] = None
    writes: Set[str] = set()
    if data is None:
        report.add("error", "SKILL.md", None, problem)
    else:
        tables, writes = _check_frontmatter(
            skill, data, report, core_names, is_core, catalog
        )
    report.writes = sorted(writes)

    used: Set[str] = set()  # tables read and write tools called
    for path, text in texts.items():
        _check_text(skill, path, text, report)
        if path.suffix.lower() == ".md":
            rel = path.relative_to(skill).as_posix()
            for first_line, content in _fences(text):
                _check_calls(
                    rel, first_line, content, catalog, tables, writes, used, report
                )
    unused_writes = sorted(writes - used)
    if unused_writes:
        report.add(
            "warning",
            "SKILL.md",
            None,
            f"{WRITES_KEY} declares tools no call uses: {' '.join(unused_writes)}",
        )
    if tables:
        # Dot-walks (group.name) read other tables without a call naming them, so
        # only flag a declared table the skill never mentions at all.
        bodies = dict(texts)
        if main in bodies:  # the declaration itself is not a mention
            bodies[main] = "\n".join(bodies[main].splitlines()[body_line - 1 :])
        everything = "\n".join(bodies.values())
        unused = sorted(
            t for t in tables - used if t not in everything.replace("\\_", "_")
        )
        if unused:
            report.add(
                "warning",
                "SKILL.md",
                None,
                f"declared but not read by any tool call: {' '.join(unused)}",
            )
    return report


def servicenow_server(manifest: Dict[str, Any]) -> Optional[str]:
    """The name of the plugin's mcpServers entry that runs this server, if any."""
    servers = manifest.get("mcpServers")
    if not isinstance(servers, dict):
        return None
    for name, spec in servers.items():
        args = spec.get("args") if isinstance(spec, dict) else None
        if isinstance(args, list) and any(
            isinstance(a, str) and PACKAGE_RE.match(a) for a in args
        ):
            return str(name)
    return None


def find_plugin_dirs(root: Path) -> List[Path]:
    """Every folder at or below ``root`` holding .claude-plugin/plugin.json (hidden skipped)."""
    found: List[Path] = []
    for dirpath, dirnames, _ in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        if (Path(dirpath) / ".claude-plugin" / "plugin.json").is_file():
            found.append(Path(dirpath))
    return found


def _check_server(name: str, spec: object, report: SkillReport) -> None:
    where = ".claude-plugin/plugin.json"
    if not isinstance(spec, dict):
        report.add("error", where, None, f"mcpServers.{name} must be an object")
        return
    if "url" in spec:
        report.add(
            "warning",
            where,
            None,
            f"mcpServers.{name} is a remote server; check that it is mcp-server-servicenow",
        )
        return
    args = spec.get("args") or []
    if spec.get("command") != "uvx" or not isinstance(args, list):
        report.add(
            "error",
            where,
            None,
            f"mcpServers.{name} must run `uvx mcp-server-servicenow[==version]`",
        )
        return
    packages = [a for a in args if isinstance(a, str) and PACKAGE_RE.match(a)]
    others = [a for a in args if a not in packages]
    if len(packages) != 1 or any(
        not isinstance(a, str) or not a.startswith("--") for a in others
    ):
        report.add(
            "error",
            where,
            None,
            f"mcpServers.{name} args must be mcp-server-servicenow[==version] "
            "plus server flags",
        )
    if "--allow-js-queries" in others:
        report.add(
            "warning",
            where,
            None,
            f"mcpServers.{name} passes --allow-js-queries, which lifts the javascript: guard",
        )
    env = spec.get("env") or {}
    if not isinstance(env, dict):
        report.add("error", where, None, f"mcpServers.{name}.env must be an object")
        return
    for key, value in env.items():
        if (
            SECRET_ENV_RE.search(str(key))
            and isinstance(value, str)
            and value
            and not ENV_REF_RE.match(value)
        ):
            report.add(
                "error",
                where,
                None,
                f"mcpServers.{name}.env.{key} holds a literal value: use ${{{key}}}",
            )


def _check_tools_json(
    plugin: Path, server: str, catalog_tools: List[Dict[str, Any]], report: SkillReport
) -> None:
    path = plugin / "evals" / "mocks" / server / "_tools.json"
    if not path.is_file():
        return
    rel = path.relative_to(plugin).as_posix()
    try:
        saved = json.loads(path.read_text(encoding="utf-8")).get("tools") or []
    except (OSError, ValueError, AttributeError):
        report.add("error", rel, None, "not a tools/list response")
        return
    want = {t["name"]: t.get("inputSchema") for t in catalog_tools}
    have = {t.get("name"): t.get("inputSchema") for t in saved if isinstance(t, dict)}
    added = sorted(set(want) - set(have))
    removed = sorted(n for n in set(have) - set(want) if isinstance(n, str))
    changed = sorted(n for n in set(want) & set(have) if want[n] != have[n])
    if added or removed or changed:
        parts = [
            f"{label}: {' '.join(names)}"
            for label, names in (
                ("missing", added),
                ("unknown", removed),
                ("changed", changed),
            )
            if names
        ]
        report.add(
            "warning",
            rel,
            None,
            "differs from this server's tools ("
            + "; ".join(parts)
            + "): regenerate it with --eval-mocks",
        )


def lint_plugin(plugin: Path, catalog_tools: List[Dict[str, Any]]) -> SkillReport:
    """Check a plugin wrapper: skills plus this server, nothing that runs other code."""
    manifest_path = plugin / ".claude-plugin" / "plugin.json"
    where = ".claude-plugin/plugin.json"
    report = SkillReport(name=f"plugin {plugin.name}", path=plugin)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        report.add("error", where, None, f"not valid JSON: {exc}")
        return report
    if not isinstance(manifest, dict):
        report.add("error", where, None, "must be a JSON object")
        return report
    if isinstance(manifest.get("name"), str):
        report.name = f"plugin {manifest['name']}"
    report.digest = "sha256:" + hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    for key in manifest:
        if key in PLUGIN_CODE_KEYS:
            report.add(
                "error",
                where,
                None,
                f"{key!r} adds code that runs as the user; a skills wrapper declares "
                "only skills and the servicenow server",
            )
        elif key not in PLUGIN_METADATA_KEYS | {"skills", "mcpServers"}:
            report.add("warning", where, None, f"unknown key {key!r}: review it")
    for rel in PLUGIN_CODE_PATHS:
        if (plugin / rel).exists():
            report.add(
                "error",
                rel,
                None,
                "Claude Code loads this location as plugin code; remove it",
            )
    skills = manifest.get("skills", "./skills/")
    for entry in skills if isinstance(skills, list) else [skills]:
        if not isinstance(entry, str):
            report.add("error", where, None, "skills must be a path or a list of paths")
            continue
        target = (plugin / entry).resolve()
        if not target.is_relative_to(plugin.resolve()) or not target.exists():
            report.add(
                "error", where, None, f"skills path {entry!r} is not a folder inside"
            )
    servers = manifest.get("mcpServers")
    if servers is None:
        report.add("warning", where, None, "no mcpServers: the skills have no tools")
        return report
    if not isinstance(servers, dict) or len(servers) != 1:
        report.add(
            "error", where, None, "mcpServers must hold exactly one server: this one"
        )
        return report
    name, spec = next(iter(servers.items()))
    _check_server(name, spec, report)
    _check_tools_json(plugin, name, catalog_tools, report)
    return report


def _catalog_tools() -> List[Dict[str, Any]]:
    return [
        t.to_mcp_tool().model_dump(mode="json", by_alias=True, exclude_none=True)
        for t in asyncio.run(registered_tools())
    ]


def lint_skills(paths: Sequence[Path]) -> LintReport:
    report = LintReport()
    catalog = tool_catalog()
    core_names = core_skill_names()
    core_root = Path(str(files("servicenow_mcp").joinpath("skills"))).resolve()
    catalog_tools: Optional[List[Dict[str, Any]]] = None
    for root in paths:
        if not root.exists():
            report.problems.append(f"{root}: no such file or folder")
            continue
        skills = find_skill_dirs(root)
        if not skills:
            report.problems.append(f"{root}: no SKILL.md found")
        for skill in skills:
            report.skills.append(lint_skill(skill, catalog, core_names, core_root))
        plugins = find_plugin_dirs(root) if root.is_dir() else []
        if plugins and catalog_tools is None:
            catalog_tools = _catalog_tools()
        for plugin in plugins:
            report.plugins.append(lint_plugin(plugin, catalog_tools or []))
    return report


def render(report: LintReport, version: str, strict: bool) -> Tuple[str, int]:
    """Doctor-style text and the exit code (1 on errors, or on warnings with strict)."""
    out = [
        f"mcp-server-servicenow {version} --validate-skills"
        + (" --strict" if strict else "")
    ]
    for problem in report.problems:
        out.append(f"error   {problem}")
    for skill in report.checked:
        state = "FAIL" if skill.errors else ("warn" if skill.warnings else "ok")
        writes = f"  writes: {' '.join(skill.writes)}" if skill.writes else ""
        out.append(f"{state:<7} {skill.name}  {skill.digest}  ({skill.path}){writes}")
        out.extend(f.render() for f in skill.findings)
    errors, warnings = report.error_count, report.warning_count
    failed = errors > 0 or (strict and warnings > 0)
    summary = f"{len(report.skills)} skills"
    if report.plugins:
        summary += f", {len(report.plugins)} plugins"
    summary += f", {errors} errors, {warnings} warnings"
    out.append(f"result: {'FAILED' if failed else 'OK'} ({summary})")
    return "\n".join(out), 1 if failed else 0
