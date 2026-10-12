"""--validate-skills: the Agent Skills spec plus this server's skill profile, offline."""

import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

import pytest

from servicenow_mcp.skill_lint import (
    MAX_FILES,
    ROLES_KEY,
    TABLES_KEY,
    WRITES_KEY,
    LintReport,
    lint_skills,
    render,
)

REPO = Path(__file__).resolve().parents[1]

GOOD = f"""---
name: my-skill
description: "Reviews SLA definitions. Use when the user asks about SLAs."
license: MIT
metadata:
  {ROLES_KEY}: "itil snc_read_only"
  {TABLES_KEY}: "task_sla contract_sla"
---

# My skill

Read [the notes](references/notes.md).

```
list_records(table_name="task_sla", query="has_breached=true^opened_atRELATIVEGT@dayofweek@ago@30", fields="task.number,sla.name", limit=50)
aggregate_records(table_name="contract_sla", group_by="collection")
```
"""


def make_skill(root: Path, files: Dict[str, str], name: str = "my-skill") -> Path:
    skill = root / name
    for rel, text in files.items():
        path = skill / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return skill


def messages(report: LintReport, level: str) -> List[str]:
    return [
        f.message for s in report.skills for f in s.findings if f.level == level
    ] + (report.problems if level == "error" else [])


@pytest.fixture
def good(tmp_path: Path) -> Path:
    return make_skill(tmp_path, {"SKILL.md": GOOD, "references/notes.md": "# Notes\n"})


def test_a_good_skill_passes(good: Path) -> None:
    report = lint_skills([good])
    assert messages(report, "error") == []
    assert messages(report, "warning") == []
    assert report.skills[0].digest.startswith("sha256:")


def test_a_parent_folder_finds_every_skill(tmp_path: Path, good: Path) -> None:
    make_skill(
        tmp_path, {"SKILL.md": GOOD.replace("my-skill", "other-skill")}, "other-skill"
    )
    make_skill(tmp_path / ".hidden", {"SKILL.md": "not checked"})
    names = sorted(s.name for s in lint_skills([tmp_path]).skills)
    assert names == ["my-skill", "other-skill"]


def test_digest_changes_with_content(tmp_path: Path, good: Path) -> None:
    before = lint_skills([good]).skills[0].digest
    (good / "references" / "notes.md").write_text("# Changed\n")
    assert lint_skills([good]).skills[0].digest != before


@pytest.mark.parametrize(
    ("frontmatter", "expected"),
    [
        ("", "must start with YAML frontmatter"),
        ("---\nname: my-skill\n", "no closing"),
        ("---\nname: [\n---\n", "not valid YAML"),
        ("---\ndescription: x\n---\n", "needs a name"),
        ("---\nname: My_Skill\ndescription: x\n---\n", "lowercase"),
        ("---\nname: other-name\ndescription: x\n---\n", "must equal the folder name"),
        ("---\nname: my-skill\n---\n", "needs a description"),
        (f"---\nname: my-skill\ndescription: {'x' * 1025}\n---\n", "at most 1024"),
        (
            f"---\nname: my-skill\ndescription: x\nmetadata:\n  {TABLES_KEY}: [a, b]\n---\n",
            "must be a string",
        ),
        (
            f'---\nname: my-skill\ndescription: x\nmetadata:\n  {TABLES_KEY}: "incident sys/user"\n---\n',
            "invalid table names",
        ),
    ],
)
def test_frontmatter_errors(tmp_path: Path, frontmatter: str, expected: str) -> None:
    skill = make_skill(tmp_path, {"SKILL.md": frontmatter + "\n# Body\n"})
    assert any(expected in m for m in messages(lint_skills([skill]), "error"))


def test_missing_license_is_a_warning(tmp_path: Path) -> None:
    skill = make_skill(
        tmp_path,
        {"SKILL.md": GOOD.replace("license: MIT\n", ""), "references/notes.md": ""},
    )
    assert messages(lint_skills([skill]), "error") == []
    assert any("no license" in m for m in messages(lint_skills([skill]), "warning"))


@pytest.mark.parametrize(
    ("rel", "expected"),
    [
        ("scripts/run.sh", "only .md, .txt and .csv"),
        ("references/data.json", "only .md, .txt and .csv"),
        (".env", "hidden files"),
        (".cache/x.md", "hidden folders"),
    ],
)
def test_file_allowlist(tmp_path: Path, rel: str, expected: str) -> None:
    skill = make_skill(
        tmp_path, {"SKILL.md": GOOD, "references/notes.md": "", rel: "x"}
    )
    assert any(expected in m for m in messages(lint_skills([skill]), "error"))


def test_symlinks_are_refused(tmp_path: Path, good: Path) -> None:
    os.symlink("/etc/hosts", good / "references" / "hosts.md")
    assert any("symlinks" in m for m in messages(lint_skills([good]), "error"))


def test_not_utf8(tmp_path: Path, good: Path) -> None:
    (good / "references" / "latin.txt").write_bytes(b"caf\xe9")
    assert any("not UTF-8" in m for m in messages(lint_skills([good]), "error"))


def test_file_count_limit(tmp_path: Path, good: Path) -> None:
    for i in range(MAX_FILES):
        (good / "references" / f"n{i}.txt").write_text("x")
    assert any("files (at most" in m for m in messages(lint_skills([good]), "error"))


@pytest.mark.parametrize(
    ("link", "level", "expected"),
    [
        ("[up](../outside.md)", "error", "leaves the skill folder"),
        ("[gone](references/missing.md)", "error", "does not exist"),
        ("[blog](https://example.com/post)", "warning", "outside ServiceNow"),
    ],
)
def test_links(tmp_path: Path, link: str, level: str, expected: str) -> None:
    (tmp_path / "outside.md").write_text("x")
    skill = make_skill(
        tmp_path,
        {"SKILL.md": GOOD + f"\n{link}\n", "references/notes.md": ""},
    )
    assert any(expected in m for m in messages(lint_skills([skill]), level))


def test_doc_links_and_anchors_are_fine(tmp_path: Path) -> None:
    body = (
        "\n[a](https://www.servicenow.com/docs/r/brazil/x.html) "
        "[b](https://github.com/ServiceNow/ServiceNowDocs/blob/753a7f0e8fac/markdown/x.md) "
        "[c](#workflows) [d](references/notes.md#top)\n"
    )
    skill = make_skill(tmp_path, {"SKILL.md": GOOD + body, "references/notes.md": ""})
    report = lint_skills([skill])
    assert messages(report, "error") == [] and messages(report, "warning") == []


@pytest.mark.parametrize(
    ("call", "level", "expected"),
    [
        ('list_records(table_name="incident")', "error", "does not declare"),
        ('list_records(table_name="task_sla/../x")', "error", "invalid table name"),
        (
            'list_records(table_name="task_sla", query="user=javascript:gs.getUserID()")',
            "error",
            "script the server refuses",
        ),
        (
            'list_records(table_name="task_sla", fields="a;b")',
            "error",
            "invalid fields",
        ),
        (
            'list_records(table_name="task_sla", order_by="a^b")',
            "error",
            "invalid order_by",
        ),
        (
            'update_record(table_name="task_sla", sys_id="<id>", data={})',
            "warning",
            "writes",
        ),
        ('list_recordz(table_name="task_sla")', "warning", "not a tool"),
        ('list_records(table_name="task_sla",', "warning", "not a parseable call"),
        ('get_update_set(sys_id="<id>")', "error", "sys_update_set"),
    ],
)
def test_tool_calls(tmp_path: Path, call: str, level: str, expected: str) -> None:
    text = GOOD + f'\n```\n{call}\nlist_records(table_name="task_sla")\n```\n'
    skill = make_skill(tmp_path, {"SKILL.md": text, "references/notes.md": ""})
    assert any(expected in m for m in messages(lint_skills([skill]), level))


def test_declared_writes(tmp_path: Path) -> None:
    call = '\n```\nupdate_record(table_name="task_sla", sys_id="<id>", data={})\n```\n'
    declared = GOOD.replace(
        f"  {TABLES_KEY}:", f'  {WRITES_KEY}: "update_record"\n  {TABLES_KEY}:'
    )
    skill = make_skill(
        tmp_path, {"SKILL.md": declared + call, "references/notes.md": ""}
    )
    report = lint_skills([skill])
    assert messages(report, "error") == [] and messages(report, "warning") == []
    assert report.skills[0].writes == ["update_record"]
    text, code = render(report, "9.9.9", strict=True)
    assert code == 0 and "writes: update_record" in text


@pytest.mark.parametrize(
    ("writes", "body", "level", "expected"),
    [
        ('"list_records"', "", "error", "not write tools"),
        ('"update_record"', "", "warning", "declares tools no call uses"),
        ("[update_record]", "", "error", "must be a string"),
    ],
)
def test_declared_writes_problems(
    tmp_path: Path, writes: str, body: str, level: str, expected: str
) -> None:
    text = GOOD.replace(
        f"  {TABLES_KEY}:", f"  {WRITES_KEY}: {writes}\n  {TABLES_KEY}:"
    )
    skill = make_skill(tmp_path, {"SKILL.md": text + body, "references/notes.md": ""})
    assert any(expected in m for m in messages(lint_skills([skill]), level))


def test_calls_need_declared_tables(tmp_path: Path) -> None:
    text = GOOD.replace(f'  {TABLES_KEY}: "task_sla contract_sla"\n', "")
    skill = make_skill(tmp_path, {"SKILL.md": text, "references/notes.md": ""})
    assert any(
        f"declare the tables in {TABLES_KEY}" in m
        for m in messages(lint_skills([skill]), "error")
    )


def test_placeholders_and_cmdb_classes(tmp_path: Path) -> None:
    text = GOOD.replace(
        '"task_sla contract_sla"', '"task_sla contract_sla cmdb_ci"'
    ) + (
        '\n```\nlist_records(table_name="<table_name>", fields="<field>")\n'
        'list_ci(class_name="cmdb_ci_server")\n```\n'
    )
    skill = make_skill(tmp_path, {"SKILL.md": text, "references/notes.md": ""})
    assert messages(lint_skills([skill]), "error") == []


def test_unused_declared_table_only_when_never_mentioned(tmp_path: Path) -> None:
    text = GOOD.replace(
        '"task_sla contract_sla"', '"task_sla contract_sla sys_user_group change_task"'
    )
    text += "\nGroups come through `sys_user_group` dot-walks.\n"
    skill = make_skill(tmp_path, {"SKILL.md": text, "references/notes.md": ""})
    warnings = messages(lint_skills([skill]), "warning")
    assert any("change_task" in m for m in warnings)
    assert not any("sys_user_group" in m for m in warnings)


@pytest.mark.parametrize(
    "secret",
    [
        "password: hunter2hunter2",
        "client_secret=abcdef123456",
        "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9xx",
        "-----BEGIN RSA PRIVATE KEY-----",
        "key QmFzZTY0RW5jb2RlZFNlY3JldFZhbHVlVGhhdElzTG9uZ0Vub3VnaA==",
    ],
)
def test_credential_like_text_warns(tmp_path: Path, secret: str) -> None:
    skill = make_skill(
        tmp_path, {"SKILL.md": GOOD, "references/notes.md": secret + "\n"}
    )
    assert any("credential" in m for m in messages(lint_skills([skill]), "warning"))


def test_placeholders_are_not_credentials(tmp_path: Path) -> None:
    notes = "password: <your password>\nSee https://github.com/ServiceNow/ServiceNowDocs/blob/753a7f0e8facb05a602b55fcb32ccba9a868c895/markdown/x.md\n"
    skill = make_skill(tmp_path, {"SKILL.md": GOOD, "references/notes.md": notes})
    assert not any("credential" in m for m in messages(lint_skills([skill]), "warning"))


def test_core_name_collision_warns_outside_the_package(tmp_path: Path) -> None:
    text = GOOD.replace("name: my-skill", "name: triaging-incidents")
    skill = make_skill(
        tmp_path, {"SKILL.md": text, "references/notes.md": ""}, "triaging-incidents"
    )
    assert any(
        "also a skill this server ships" in m
        for m in messages(lint_skills([skill]), "warning")
    )


def test_missing_path_is_an_error(tmp_path: Path) -> None:
    report = lint_skills([tmp_path / "nope"])
    assert report.error_count == 1
    report = lint_skills([tmp_path])
    assert "no SKILL.md found" in report.problems[0]


def test_render_and_strict(tmp_path: Path) -> None:
    skill = make_skill(
        tmp_path,
        {"SKILL.md": GOOD.replace("license: MIT\n", ""), "references/notes.md": ""},
    )
    report = lint_skills([skill])
    text, code = render(report, "9.9.9", strict=False)
    assert code == 0 and text.splitlines()[-1].startswith("result: OK")
    assert "warn    my-skill  sha256:" in text
    text, code = render(report, "9.9.9", strict=True)
    assert code == 1 and "result: FAILED" in text


def test_shipped_skills_pass() -> None:
    """The core skills are the reference implementation of the profile."""
    report = lint_skills([REPO / "src" / "servicenow_mcp" / "skills"])
    assert len(report.skills) == 5
    assert messages(report, "error") == []
    assert messages(report, "warning") == []  # CI runs them with --strict


def test_cli_exit_codes(tmp_path: Path, good: Path) -> None:
    bad = make_skill(tmp_path, {"SKILL.md": "no frontmatter"}, "bad-skill")
    cmd = [sys.executable, "-m", "servicenow_mcp.cli", "--validate-skills"]
    env = {**os.environ, "SERVICENOW_INSTANCE_URL": ""}
    ok = subprocess.run([*cmd, str(good)], capture_output=True, text=True, env=env)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert "result: OK" in ok.stdout
    fail = subprocess.run([*cmd, str(bad)], capture_output=True, text=True, env=env)
    assert fail.returncode == 1 and "result: FAILED" in fail.stdout
