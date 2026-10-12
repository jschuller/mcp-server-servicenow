#!/usr/bin/env python3
"""Check ServiceNowDocs citations in Markdown files (standard library and git only).

A citation is a link to a file in the ServiceNow/ServiceNowDocs repository pinned to
a commit:

    https://github.com/ServiceNow/ServiceNowDocs/blob/<commit>/markdown/<path>.md

For each one, against a blobless clone of ServiceNowDocs:
- error   when the commit or the path at that commit does not exist (a typo, or a
          link that never worked);
- error   when the path is gone from the head of its release branch (the page was
          removed or moved: re-cite it);
- warning when the page changed since the cited commit (re-read it and re-cite).

The release branch comes from a ``servicenow.com/docs/r/<release>/`` link on the same
line, else ``--branch`` (default ``brazil``). Never checks servicenow.com by HTTP: the
docs site answers 200 for pages that do not exist.

    check_citations.py [--docs-clone DIR] [--branch brazil] PATH [PATH ...]

Exit code 1 when there is any error. Inside GitHub Actions the findings are also
printed as ::error/::warning annotations.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

REPO_URL = "https://github.com/ServiceNow/ServiceNowDocs.git"
CITE_RE = re.compile(
    r"https://github\.com/ServiceNow/ServiceNowDocs/blob/([0-9a-f]{7,40})/([^\s)\]#?\"'>]+)"
)
RELEASE_RE = re.compile(r"servicenow\.com/docs/r/([a-z]+)/")
RELEASES = {"brazil", "australia", "zurich", "yokohama", "xanadu", "washingtondc"}
ANNOTATE = os.environ.get("GITHUB_ACTIONS") == "true"


def git(repo: Path, *args: str) -> Tuple[int, str]:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True
    )
    return proc.returncode, proc.stdout.strip()


def markdown_files(paths: List[str]) -> Iterator[Path]:
    for raw in paths:
        p = Path(raw)
        if p.is_file() and p.suffix == ".md":
            yield p
        elif p.is_dir():
            for f in sorted(p.rglob("*.md")):
                if not any(part.startswith(".") for part in f.relative_to(p).parts):
                    yield f


def citations(
    paths: List[str], default_branch: str
) -> Iterator[Tuple[Path, int, str, str, str]]:
    """(file, line, commit, path, branch) for every citation."""
    for f in markdown_files(paths):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            m = RELEASE_RE.search(line)
            branch = m.group(1) if m and m.group(1) in RELEASES else default_branch
            for commit, path in CITE_RE.findall(line):
                yield f, n, commit, path, branch


def blobless_clone(branches: List[str]) -> Path:
    target = Path(tempfile.mkdtemp(prefix="servicenowdocs-"))
    subprocess.run(
        ["git", "clone", "--quiet", "--filter=blob:none", "--no-checkout",
         "--single-branch", "--branch", branches[0], REPO_URL, str(target)],
        check=True,
    )
    for b in branches[1:]:
        subprocess.run(
            ["git", "-C", str(target), "fetch", "--quiet", "--filter=blob:none",
             "origin", f"+refs/heads/{b}:refs/remotes/origin/{b}"],
            check=True,
        )
    return target


def head_ref(repo: Path, branch: str) -> Optional[str]:
    for ref in (f"origin/{branch}", branch):
        if git(repo, "rev-parse", "--verify", "--quiet", ref)[0] == 0:
            return ref
    return None


def report(level: str, f: Path, line: int, message: str) -> None:
    print(f"{level:<7} {f}:{line}  {message}")
    if ANNOTATE:
        print(f"::{level} file={f},line={line}::{message}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--docs-clone", help="an existing ServiceNowDocs clone to use")
    parser.add_argument("--branch", default="brazil", help="release branch by default")
    args = parser.parse_args(argv)

    found = list(citations(args.paths, args.branch))
    if not found:
        print("citations: none found")
        return 0
    branches = sorted({c[4] for c in found}, key=lambda b: b != args.branch)
    repo = Path(args.docs_clone) if args.docs_clone else blobless_clone(branches)
    try:
        return check(repo, found, branches)
    finally:
        if not args.docs_clone:
            shutil.rmtree(repo, ignore_errors=True)


def check(repo: Path, found: List[Tuple[Path, int, str, str, str]], branches: List[str]) -> int:
    errors = warnings = 0
    heads: Dict[str, Optional[str]] = {b: head_ref(repo, b) for b in branches}
    for f, line, commit, path, branch in found:
        if git(repo, "cat-file", "-e", f"{commit}^{{commit}}")[0] != 0:
            report("error", f, line, f"commit {commit} is not in ServiceNowDocs")
            errors += 1
            continue
        code, cited = git(repo, "rev-parse", f"{commit}:{path}")
        if code != 0:
            report("error", f, line, f"{path} does not exist at {commit}")
            errors += 1
            continue
        head = heads[branch]
        if head is None:
            report("error", f, line, f"release branch {branch} not found")
            errors += 1
            continue
        code, current = git(repo, "rev-parse", f"{head}:{path}")
        if code != 0:
            report("error", f, line, f"{path} is gone from {branch}: re-cite the current page")
            errors += 1
        elif current != cited:
            report("warning", f, line, f"{path} changed on {branch} since {commit}: re-read and re-cite")
            warnings += 1
    print(f"citations: {len(found)} checked, {errors} errors, {warnings} warnings")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
