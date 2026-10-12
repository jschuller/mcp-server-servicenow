"""actions/validate-skills/check_citations.py against a tiny local docs repository."""

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "actions" / "validate-skills" / "check_citations.py"


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def docs(tmp_path: Path) -> tuple[Path, str]:
    """A repo on branch brazil: commit 1 adds a.md and b.md, commit 2 edits a.md and deletes b.md."""
    repo = tmp_path / "docs"
    (repo / "markdown").mkdir(parents=True)
    git(tmp_path, "init", "-q", "-b", "brazil", str(repo))
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    (repo / "markdown" / "a.md").write_text("one\n")
    (repo / "markdown" / "b.md").write_text("bee\n")
    (repo / "markdown" / "c.md").write_text("stable\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "1")
    first = git(repo, "rev-parse", "HEAD")
    (repo / "markdown" / "a.md").write_text("two\n")
    (repo / "markdown" / "b.md").unlink()
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "2")
    return repo, first


def run(docs_repo: Path, *paths: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--docs-clone", str(docs_repo), *map(str, paths)],
        capture_output=True,
        text=True,
    )


def cite(commit: str, path: str) -> str:
    return (
        "[Page](https://www.servicenow.com/docs/r/brazil/x.html) · "
        f"[source](https://github.com/ServiceNow/ServiceNowDocs/blob/{commit}/markdown/{path})\n"
    )


def test_unchanged_citation_passes(tmp_path: Path, docs) -> None:
    repo, first = docs
    (tmp_path / "s.md").write_text(cite(first[:12], "c.md"))
    out = run(repo, tmp_path / "s.md")
    assert out.returncode == 0, out.stdout
    assert "1 checked, 0 errors, 0 warnings" in out.stdout


def test_changed_page_warns(tmp_path: Path, docs) -> None:
    repo, first = docs
    (tmp_path / "s.md").write_text(cite(first, "a.md"))
    out = run(repo, tmp_path / "s.md")
    assert out.returncode == 0
    assert "changed on brazil" in out.stdout


@pytest.mark.parametrize(
    ("commit", "path", "expected"),
    [
        (None, "b.md", "gone from brazil"),
        (None, "nope.md", "does not exist at"),
        ("0123456789ab", "a.md", "not in ServiceNowDocs"),
    ],
)
def test_errors(tmp_path: Path, docs, commit, path, expected) -> None:
    repo, first = docs
    (tmp_path / "s.md").write_text(cite(commit or first, path))
    out = run(repo, tmp_path / "s.md")
    assert out.returncode == 1
    assert expected in out.stdout


def test_no_citations(tmp_path: Path, docs) -> None:
    repo, _ = docs
    (tmp_path / "s.md").write_text("no links here\n")
    out = run(repo, tmp_path)
    assert out.returncode == 0 and "none found" in out.stdout


def test_shipped_skill_citations_are_well_formed() -> None:
    """Every core citation pins a commit and a markdown/ path (checked against
    GitHub in CI by the validate-skills Action)."""
    sys.path.insert(0, str(SCRIPT.parent))
    try:
        from check_citations import citations
    finally:
        sys.path.pop(0)
    found = list(citations([str(REPO / "src" / "servicenow_mcp" / "skills")], "brazil"))
    assert len(found) >= 20
    assert all(path.startswith("markdown/") for _, _, _, path, _ in found)
