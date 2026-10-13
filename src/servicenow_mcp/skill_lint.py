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
declare only skills and one ``mcpServers`` entry that runs ``uvx mcp-server-servicenow``
with this server's own settings, because ``claude plugin eval`` runs a plugin's hooks,
agents and servers as the person evaluating it. Skills may not carry code either: no
hooks, pre-approved tools or ``!`command``` shell injection. The wrapper's
``evals/mocks/<server>/_tools.json`` must match this server's tools.

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
    "metadata",
}
# Every other manifest key is refused; these add code that runs as the user.
PLUGIN_CODE_KEYS = {
    "hooks",
    "agents",
    "commands",
    "monitors",
    "lspServers",
    "outputStyles",
    "mods",
    "settings",
    "workflows",
    "dependencies",
    "userConfig",
    "channels",
    "experimental",
}
# Locations Claude Code (or uvx) loads from a plugin folder without a manifest key.
PLUGIN_CODE_PATHS = {
    "hooks": "Claude Code loads this location as plugin code; remove it",
    "agents": "Claude Code loads this location as plugin code; remove it",
    "commands": "Claude Code loads this location as plugin code; remove it",
    "monitors": "Claude Code loads this location as plugin code; remove it",
    "output-styles": "Claude Code loads this location as plugin code; remove it",
    "workflows": "Claude Code loads this location as plugin code; remove it",
    "themes": "Claude Code loads this location as plugin code; remove it",
    "bin": "Claude Code puts this folder on the shell's PATH; remove it",
    ".mcp.json": "Claude Code loads this location as plugin code; remove it",
    ".lsp.json": "Claude Code loads this location as plugin code; remove it",
    "settings.json": "Claude Code loads this location as plugin code; remove it",
    "package.json": "Claude Code installs a plugin's packages when it loads; remove it",
    "uv.toml": "uv reads it, so it can change which package uvx runs; remove it",
}
UV_SETTINGS_RE = re.compile(r"^\s*\[+\s*tool\.uv\b", re.M)
# The plugin's server may set only this server's own settings, and pass only these flags.
SERVER_ENV = {
    "SERVICENOW_INSTANCE_URL",
    "SERVICENOW_AUTH_TYPE",
    "SERVICENOW_USERNAME",
    "SERVICENOW_PASSWORD",
    "SERVICENOW_CLIENT_ID",
    "SERVICENOW_CLIENT_SECRET",
    "SERVICENOW_TOKEN_URL",
    "SERVICENOW_API_KEY",
    "SERVICENOW_API_KEY_HEADER",
    "SERVICENOW_TIMEOUT",
    "SERVICENOW_DEBUG",
    "SERVICENOW_READ_ONLY",
    "SERVICENOW_ALLOW_JS_QUERIES",
    "SERVICENOW_AUDIT_LOG",
}
SECRET_ENV = {"SERVICENOW_PASSWORD", "SERVICENOW_CLIENT_SECRET", "SERVICENOW_API_KEY"}
# Where the server sends those credentials: a skills repository mustn't choose it.
HOST_ENV = {"SERVICENOW_INSTANCE_URL", "SERVICENOW_TOKEN_URL"}
SERVER_FLAGS = {"--read-only", "--debug", "--allow-js-queries"}
SERVER_SPEC_KEYS = {"type", "command", "args", "env"}
ENV_REF_RE = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*(:-[^}]*)?\}$")
# Settings whose literal or default value changes what the server does on the user's machine.
SAFE_ENV_VALUES = {
    "SERVICENOW_ALLOW_JS_QUERIES": (
        re.compile(
            r"^(false|0|no|)$|^\$\{[A-Za-z_][A-Za-z0-9_]*(:-(false|0|no)?)?\}$", re.I
        ),
        "lifts the javascript: guard",
    ),
    "SERVICENOW_AUDIT_LOG": (
        re.compile(r"^(stderr|off|)$|^\$\{[A-Za-z_][A-Za-z0-9_]*(:-(stderr|off)?)?\}$"),
        "writes the audit log to a file on the user's machine",
    ),
}

# SKILL.md frontmatter: the Agent Skills fields plus Claude Code's own.
SKILL_CODE_KEYS = {
    "hooks": "registers hooks that run commands",
    "allowed-tools": "pre-approves tools for the user",
    "shell": "runs !`command` shell injection",
}
SKILL_CONTEXT_KEYS = {"context", "agent", "background"}
SKILL_KEYS = (
    {
        "name",
        "description",
        "license",
        "compatibility",
        "metadata",
        "when_to_use",
        "argument-hint",
        "arguments",
        "disable-model-invocation",
        "user-invocable",
        "model",
        "effort",
        "paths",
        "disallowed-tools",
    }
    | set(SKILL_CODE_KEYS)
    | SKILL_CONTEXT_KEYS
)
# Claude Code runs !`command` (after a line start or whitespace, in JavaScript's sense,
# which includes U+FEFF) and ```! blocks (anywhere in the text) when a skill loads.
SHELL_INJECTION_RE = re.compile(r"(?:^|[\s\ufeff])!`|```\s*!")
# Folders that hold tooling, not skills, when searching a repository.
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".tox",
    ".nox",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
}


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
    declared_skills: List[Path] = field(
        default_factory=list
    )  # a plugin's skill folders
    declared_plugins: List[Path] = field(
        default_factory=list
    )  # a marketplace's plugin folders

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


def _walk(root: Path) -> Iterator[Tuple[Path, List[str], List[str]]]:
    """os.walk without links or tooling folders; hidden folders are searched too,
    because skill installers read folders such as .claude/skills. A tooling folder that
    holds a SKILL.md is a skill: Claude Code loads skills/node_modules/SKILL.md."""
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        dirnames[:] = sorted(
            d
            for d in dirnames
            if (d not in SKIP_DIRS or (here / d / "SKILL.md").is_file())
            and not (here / d).is_symlink()
        )
        yield here, dirnames, filenames


def find_skill_dirs(root: Path) -> List[Path]:
    """Every folder at or below ``root`` that holds a SKILL.md."""
    if (root / "SKILL.md").is_file():
        return [root]
    found: List[Path] = []
    for here, dirnames, filenames in _walk(root):
        if "SKILL.md" in filenames:
            found.append(here)
            dirnames[:] = []  # a skill's own subfolders belong to it
    return found


def find_linked_dirs(root: Path) -> List[Path]:
    """Symlinked folders below ``root``: installers may follow them, this check doesn't."""
    if not root.is_dir() or (root / "SKILL.md").is_file():
        return []  # a skill's own links are reported with the skill
    found: List[Path] = []
    for dirpath, dirnames, _ in os.walk(root):
        here = Path(dirpath)
        found.extend(here / d for d in dirnames if (here / d).is_symlink())
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
    return sorted(found)


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
    for key in data:
        if key in SKILL_CODE_KEYS:
            report.add(
                "error",
                "SKILL.md",
                None,
                f"{key!r} {SKILL_CODE_KEYS[key]}; a ServiceNow skill is instructions only",
            )
        elif key in SKILL_CONTEXT_KEYS:
            report.add(
                "warning",
                "SKILL.md",
                None,
                f"{key!r} runs the skill in another context: review it",
            )
        elif key not in SKILL_KEYS:
            report.add(
                "warning",
                "SKILL.md",
                None,
                f"{key!r} is not an Agent Skills or Claude Code field: review it",
            )

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


def _check_writes(
    rel: str,
    text: str,
    catalog: ToolCatalog,
    writes: Set[str],
    used: Set[str],
    report: SkillReport,
) -> None:
    """Every write-tool call anywhere in the text, in code blocks or prose."""
    pattern = re.compile(r"\b(" + "|".join(sorted(catalog.write)) + r")\s*\(")
    for n, line in enumerate(text.splitlines(), 1):
        for tool in dict.fromkeys(pattern.findall(line)):
            used.add(tool)
            if tool not in writes:
                report.add(
                    "warning",
                    rel,
                    n,
                    f"{tool}() writes to the instance: declare it in {WRITES_KEY},"
                    " and say in the skill to ask before writing",
                )


def _check_shell(rel: str, text: str, report: SkillReport) -> None:
    """Claude Code runs !`command` and ```! blocks when the skill loads."""
    for n, line in enumerate(text.splitlines(), 1):
        fence = FENCE_RE.match(line)
        if SHELL_INJECTION_RE.search(line) or (
            fence and fence.group(3).lstrip().startswith("!")
        ):
            report.add(
                "error",
                rel,
                n,
                "!`command` shell injection runs on the user's machine; a ServiceNow "
                "skill is instructions only",
            )


def _check_text(skill: Path, path: Path, text: str, report: SkillReport) -> None:
    rel = path.relative_to(skill).as_posix()
    skill_root = skill.resolve()
    _check_shell(rel, text, report)
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

    parent = skill.resolve().parent
    # The packaged skills, or their source in a checkout of this repository.
    is_core = (core_root is not None and parent == core_root) or parent.parts[-2:] == (
        "servicenow_mcp",
        "skills",
    )
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
            _check_writes(rel, text, catalog, writes, used, report)
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
    """Every folder at or below ``root`` holding .claude-plugin/plugin.json."""
    return [
        here
        for here, _, _ in _walk(root)
        if (here / ".claude-plugin" / "plugin.json").is_file()
    ]


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
    extra = sorted(set(spec) - SERVER_SPEC_KEYS)
    if extra or spec.get("type", "stdio") != "stdio":
        report.add(
            "error",
            where,
            None,
            f"mcpServers.{name} may set only command, args and env "
            f"(found {', '.join(extra) or 'type ' + str(spec.get('type'))})",
        )
    args = spec.get("args") or []
    if (
        spec.get("command") != "uvx"
        or not isinstance(args, list)
        or not args
        or not all(isinstance(a, str) for a in args)
        or not PACKAGE_RE.match(args[0])
    ):
        # uvx reads options before the package name (--from, --with, --index-url), so
        # the package comes first and only this server's flags follow it.
        report.add(
            "error",
            where,
            None,
            f"mcpServers.{name} must run `uvx mcp-server-servicenow[==version]` with the "
            "package first",
        )
        return
    for flag in args[1:]:
        if flag not in SERVER_FLAGS:
            report.add(
                "error",
                where,
                None,
                f"mcpServers.{name} passes {flag!r}: only {', '.join(sorted(SERVER_FLAGS))} "
                "may follow the package; put settings in env",
            )
    if "--allow-js-queries" in args:
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
        if key not in SERVER_ENV:
            report.add(
                "error",
                where,
                None,
                f"mcpServers.{name}.env.{key} is not a setting of this server "
                "(only SERVICENOW_* settings it reads)",
            )
            continue
        if not isinstance(value, str):
            report.add(
                "error", where, None, f"mcpServers.{name}.env.{key} must be a string"
            )
            continue
        own_ref = value in (f"${{{key}}}", f"${{{key}:-}}")
        if key in HOST_ENV and value and not own_ref:
            report.add(
                "error",
                where,
                None,
                f"mcpServers.{name}.env.{key} sets a host or default: use ${{{key}}}, "
                "so the user's credentials go only to the instance they choose",
            )
        if key in SECRET_ENV and value and not own_ref:
            report.add(
                "error",
                where,
                None,
                f"mcpServers.{name}.env.{key} holds a literal value or default: "
                f"use ${{{key}}}",
            )
        safe = SAFE_ENV_VALUES.get(key)
        if safe and not safe[0].match(value):
            report.add(
                "warning",
                where,
                None,
                f"mcpServers.{name}.env.{key}={value!r} {safe[1]}",
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

    def shape(tool: Dict[str, Any]) -> Tuple[str, ...]:
        # What the agent sees of a tool: its description, schema and hints.
        return tuple(
            json.dumps(tool.get(k), sort_keys=True)
            for k in ("description", "inputSchema", "annotations")
        )

    want = {t["name"]: shape(t) for t in catalog_tools}
    have = {t.get("name"): shape(t) for t in saved if isinstance(t, dict)}
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


def _check_grader(
    rel: str,
    data: Dict[str, Any],
    plugin_name: str,
    server: Optional[str],
    skill_names: Set[str],
    report: SkillReport,
) -> None:
    """A tool_used grader must name this plugin's skills and tools, or it can never pass."""
    if data.get("type") != "tool_used":
        return
    tool, match = data.get("tool"), data.get("input_match")
    if tool == "Skill" and isinstance(match, str) and skill_names:
        try:
            pattern = re.compile(match)
        except re.error as exc:
            report.add("error", rel, None, f"input_match is not a valid pattern: {exc}")
            return
        candidates = [
            text
            for name in skill_names
            for text in (f'"skill": "{name}"', f'"skill": "{plugin_name}:{name}"')
        ]
        if not any(pattern.search(text) for text in candidates):
            report.add(
                "warning",
                rel,
                None,
                "input_match names none of this plugin's skills "
                f"({', '.join(sorted(skill_names))}); was a skill renamed?",
            )
    prefix = f"mcp__plugin_{plugin_name}_{server}__"
    if isinstance(tool, str) and tool.startswith("mcp__plugin_") and server:
        if not tool.startswith(prefix):
            report.add(
                "warning",
                rel,
                None,
                f"tool {tool} doesn't match this plugin's tools ({prefix}<tool>); "
                "was the plugin or server renamed?",
            )


def _check_eval_files(
    plugin: Path,
    report: SkillReport,
    plugin_name: str = "",
    server: Optional[str] = None,
    skill_names: Optional[Set[str]] = None,
) -> None:
    """Case, grader and mock files need YAML frontmatter that parses, or the case is skipped."""
    evals = plugin / "evals"
    if not evals.is_dir():
        return
    for path in sorted(evals.rglob("*.md")):
        rel = path.relative_to(plugin).as_posix()
        if "/results/" in f"/{rel}" or "/.replay/" in f"/{rel}":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if not text.startswith("---"):
            continue  # a mock body without frontmatter is fine
        data, _, problem = _frontmatter(text)
        if data is None:
            report.add(
                "error", rel, None, f"{problem}; claude plugin eval skips this file"
            )
        elif "/graders/" in f"/{rel}":
            _check_grader(rel, data, plugin_name, server, skill_names or set(), report)


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
            report.add(
                "error",
                where,
                None,
                f"{key!r} is not allowed in a skills wrapper: it may add behaviour; "
                "declare only metadata, skills and the servicenow server",
            )
    for rel, why in PLUGIN_CODE_PATHS.items():
        if (plugin / rel).exists() or (plugin / rel).is_symlink():
            report.add("error", rel, None, why)
    pyproject = plugin / "pyproject.toml"
    if pyproject.is_file() and UV_SETTINGS_RE.search(
        pyproject.read_text(encoding="utf-8", errors="replace")
    ):
        report.add(
            "error",
            "pyproject.toml",
            None,
            "[tool.uv] settings can change which package uvx runs; remove them",
        )
    skill_names: Set[str] = set()
    skills = manifest.get("skills")
    entries = (
        skills
        if isinstance(skills, list)
        else [skills]
        if skills is not None
        else (["./skills/"] if (plugin / "skills").exists() else [])
    )
    for entry in entries:
        if not isinstance(entry, str):
            report.add("error", where, None, "skills must be a path or a list of paths")
            continue
        path = plugin / entry
        target = path.resolve()
        if path.is_symlink():
            report.add("error", where, None, f"skills path {entry!r} is a symlink")
        elif not target.is_relative_to(plugin.resolve()) or not target.is_dir():
            report.add(
                "error", where, None, f"skills path {entry!r} is not a folder inside"
            )
        else:
            for child in sorted(target.iterdir()):
                if child.is_symlink():
                    report.add(
                        "error",
                        where,
                        None,
                        f"skills path {entry!r} holds a symlink ({child.name}); "
                        "Claude Code follows it, this check doesn't",
                    )
            declared = find_skill_dirs(target)
            report.declared_skills.extend(declared)
            skill_names.update(p.name for p in declared)
    servers = manifest.get("mcpServers")
    server_name = (
        str(next(iter(servers)))
        if isinstance(servers, dict) and len(servers) == 1
        else None
    )
    _check_eval_files(
        plugin, report, str(manifest.get("name") or ""), server_name, skill_names
    )
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


MARKETPLACE_KEYS = {
    "$schema",
    "name",
    "owner",
    "description",
    "version",
    "metadata",
    "plugins",
}
MARKETPLACE_ENTRY_KEYS = PLUGIN_METADATA_KEYS | {"source", "category", "tags"}


def find_marketplace_dirs(root: Path) -> List[Path]:
    """Every folder at or below ``root`` holding .claude-plugin/marketplace.json."""
    return [
        here
        for here, _, _ in _walk(root)
        if (here / ".claude-plugin" / "marketplace.json").is_file()
    ]


def lint_marketplace(market: Path) -> SkillReport:
    """Check a marketplace: it may only list plugin folders in this repository, which
    are then checked as plugins. Claude Code installs whatever an entry describes,
    including components written into the entry and plugins from other sources."""
    path = market / ".claude-plugin" / "marketplace.json"
    where = ".claude-plugin/marketplace.json"
    report = SkillReport(name=f"marketplace {market.name}", path=market)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        report.add("error", where, None, f"not valid JSON: {exc}")
        return report
    if not isinstance(data, dict):
        report.add("error", where, None, "must be a JSON object")
        return report
    if isinstance(data.get("name"), str):
        report.name = f"marketplace {data['name']}"
    report.digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    for key in data:
        if key not in MARKETPLACE_KEYS:
            report.add(
                "error",
                where,
                None,
                f"{key!r} is not allowed in a skills marketplace: it may add behaviour",
            )
    plugins = data.get("plugins")
    if not isinstance(plugins, list):
        report.add("error", where, None, "plugins must be a list")
        return report
    for i, entry in enumerate(plugins):
        if not isinstance(entry, dict):
            report.add("error", where, None, f"plugins[{i}] must be an object")
            continue
        for key in entry:
            if key not in MARKETPLACE_ENTRY_KEYS:
                report.add(
                    "error",
                    where,
                    None,
                    f"plugins[{i}].{key} is not allowed: an entry only points at a "
                    "plugin folder, whose plugin.json declares its skills and server",
                )
        source = entry.get("source")
        target = (market / source).resolve() if isinstance(source, str) else None
        if (
            target is None
            or (market / str(source)).is_symlink()
            or not target.is_relative_to(market.resolve())
            or not (target / ".claude-plugin" / "plugin.json").is_file()
        ):
            report.add(
                "error",
                where,
                None,
                f"plugins[{i}].source must be a folder in this repository holding "
                ".claude-plugin/plugin.json; any other source installs code this "
                "check never saw",
            )
        else:
            report.declared_plugins.append(target)
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
    markets: List[SkillReport] = []
    for root in paths:
        if not root.exists():
            report.problems.append(f"{root}: no such file or folder")
            continue
        skills = find_skill_dirs(root)
        if not skills:
            report.problems.append(f"{root}: no SKILL.md found")
        for linked in find_linked_dirs(root):
            report.problems.append(
                f"{linked}: a symlinked folder; skill installers may follow it, and this "
                "check does not"
            )
        for skill in skills:
            report.skills.append(lint_skill(skill, catalog, core_names, core_root))
        plugins = find_plugin_dirs(root) if root.is_dir() else []
        if plugins and catalog_tools is None:
            catalog_tools = _catalog_tools()
        for plugin in plugins:
            report.plugins.append(lint_plugin(plugin, catalog_tools or []))
        if root.is_dir():
            markets.extend(lint_marketplace(m) for m in find_marketplace_dirs(root))
    # A marketplace may list plugin folders the search skips; Claude Code installs them
    # all the same, so check them too.
    seen_plugins = {p.path.resolve() for p in report.plugins}
    for market in markets:
        for plugin in market.declared_plugins:
            if plugin not in seen_plugins:
                seen_plugins.add(plugin)
                if catalog_tools is None:
                    catalog_tools = _catalog_tools()
                report.plugins.append(lint_plugin(plugin, catalog_tools))
    report.plugins.extend(markets)
    # A plugin's skills paths may point where the search doesn't go (node_modules, .venv);
    # Claude Code loads those skills all the same, so check them too.
    seen = {s.path.resolve() for s in report.skills}
    for plugin_report in report.plugins:
        for skill in plugin_report.declared_skills:
            if skill.resolve() not in seen:
                seen.add(skill.resolve())
                report.skills.append(lint_skill(skill, catalog, core_names, core_root))
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
