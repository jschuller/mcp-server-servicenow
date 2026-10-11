# Releasing

Runbook for cutting a release. Written so a maintainer — human or AI — can
execute it cold. The v0.6.1 release (2026-08-13) is the reference run.

## How publishing works

Creating a GitHub release fires two workflows **from the tag's commit**:

1. **`publish.yml`** → PyPI via OIDC Trusted Publishing (no tokens anywhere).
   Fails fast if the tag doesn't match the pyproject version.
2. **`publish-mcp.yml`** → MCP Registry. Waits for PyPI to actually serve the
   version first (PyPI takes ~1–2 min to propagate; the registry validates
   against it, and both workflows start at the same instant).

PyPI versions are **immutable** — a workflow fix on main requires re-cutting
the release (see Failure modes).

## Pre-flight

1. **Version bump** — one version, five fields (CI's "Check version
   consistency" step enforces agreement):
   - `pyproject.toml` → `version`
   - `src/servicenow_mcp/__init__.py` → `__version__`
   - `server.json` → top-level `version` **and** `packages[0].version`
   - `.claude-plugin/plugin.json` → `version` (missed in v0.6.1 — hence the check)

   Then `uv lock` (the lockfile records the project's own version), a
   `CHANGELOG.md` section (`## [X.Y.Z] - YYYY-MM-DD`), and the README
   version-history line.

2. **Verification gates** — all of these, no skips:

   ```sh
   uv run ruff check src/ tests/
   uv run ruff format --check src/ tests/
   uv run mypy
   uv run pytest tests/ --ignore=tests/integration     # unit suite
   uv run --with build,twine python -m build
   uv run --with build,twine twine check --strict dist/*
   uv run pytest tests/integration/ -v                 # live E2E (below)
   ```

   The live checks read credentials from the environment only — start them
   under a secret-store launcher, never from a file:

   ```sh
   with-secrets SERVICENOW_API_KEY=svc/homelab/servicenow-<pdi>-apikey -- env \
     SERVICENOW_INSTANCE_URL=https://<pdi>.service-now.com \
     SERVICENOW_AUTH_TYPE=api_key \
     sh -c 'uv run pytest tests/integration/ -v -rs && uv run python scripts/stdio_smoke.py --profile readonly'
   ```

   Tools the identity is refused are skipped with the missing grant named.
   The integration suite needs an awake PDI.
   If it fails with `Got HTML instead of JSON`, the instance is
   **hibernating**: open
   `https://developer.servicenow.com/dev.do#!/home?wu=true` in a logged-in
   browser, then poll the REST endpoint until it returns
   `content-type: application/json` (~1–2 min). Quote URLs containing `?`
   in zsh or the curl probe silently never runs.

3. **Real-client check** (the unit suite drives an in-memory client; these
   surfaces behave differently):
   - Claude Code: `claude mcp add servicenow-dev -- uv run --directory . mcp-server-servicenow …`,
     then update a scratch incident — Claude Code's permission prompt must
     appear before the write tool runs.
   - Claude Desktop: point `claude_desktop_config.json` at the local build;
     a read and a scratch update work.
   - Plugin: `claude --plugin-dir .` with only `SERVICENOW_INSTANCE_URL/USERNAME/PASSWORD`
     set must start (the `${VAR:-default}` passthrough check).
   - the four `skill://…/SKILL.md` resources list and read (Claude Code `/mcp` → resources).
   - Run Claude Code as `command claude …` if your shell aliases `claude`
     (e.g. to `--dangerously-skip-permissions`), or the permission checks
     are skipped.
   - Codex: `codex mcp add … -- uv run --directory . mcp-server-servicenow --read-only`,
     then `codex exec` a read question — read-only tools run without approval,
     a skill is readable via `read_mcp_resource`, a write tool is refused by
     `codex exec`; in the TUI a write tool shows Codex's approval prompt.
   - pi (1.0+): `pi mcp add … --exposure direct -- uv run --directory . mcp-server-servicenow`,
     `pi mcp list` must report 12/19 tools and 15 resources.

4. Push to main and wait for CI green — the test matrix (3.11–3.14)
   plus the `package` job (version consistency, `uv lock --check`,
   build + twine).

## Cutting the release

```sh
gh release create vX.Y.Z --target main --title "..." --notes-file notes.md
```

The tag must be exactly `v` + the pyproject version.

## Post-release verification (do not skip)

1. PyPI serves it (~75s on v0.6.1):
   `curl -s -o /dev/null -w '%{http_code}' 'https://pypi.org/pypi/mcp-server-servicenow/X.Y.Z/json'` → 200
2. Both publish workflows concluded `success` (`gh run list`).
3. Registry lists it as latest:
   `curl -s 'https://registry.modelcontextprotocol.io/v0/servers?search=io.github.jschuller/mcp-server-servicenow'`
   → newest entry `isLatest: true`.
4. Fresh-install smoke test:
   `uvx --no-cache mcp-server-servicenow==X.Y.Z --help`

## Failure modes & recovery

| Symptom | Cause / fix |
|---|---|
| PyPI `invalid-publisher` | Trusted-publisher claims must match exactly: owner `jschuller`, repo `mcp-server-servicenow`, workflow `publish.yml`, environment blank. |
| Tag/version mismatch error in publish.yml | Release was cut from the wrong commit or a bump was missed. `gh release delete vX.Y.Z --cleanup-tag`, fix, recreate with `--target main`. Safe **only** while PyPI doesn't have the version yet. |
| Registry publish failed anyway | Check `publish.yml` succeeded first, then `gh run rerun <id>` once PyPI serves the version. |
| Packaging/metadata breakage | Surfaces in CI's `package` job pre-release, not on release day — keep that job green. |

**Yank policy:** keep 0.5.1 unyanked — it is the last release without the
FastMCP 4 beta pin and the deliberate fallback for pre-release-averse users.

## Triage protocol for dependency PRs

Learned from PR #10 (a plausible-looking community PR that would have made the
package uninstallable):

1. Does the claimed version **exist on PyPI**? Check before reading further.
2. Review the **raw diff**, not the PR description — they disagreed in #10.
3. Reproduce: `git fetch origin pull/N/head:pr-N` into a scratch worktree,
   run `uv lock`. CI's `uv lock --check` now also catches conflicting pins.
4. Decline with the captured evidence quoted and a link to the tracking
   issue (see #10 for the template). Stay polite — real contributor fixes
   do land (#5).

## Security posture

Current: OIDC trusted publishing (no long-lived secrets), all Actions pinned
to commit SHAs, fail-closed HTTP serving, Dependabot + Renovate, strict twine
metadata check, ruff rule set and mypy major version bounded so unpinned CI
installs can't shift behavior underneath previously-clean code.

Considered and deliberately not done yet: GitHub environment protection on
the publish workflows (requires registering the environment name with the
PyPI publisher), a scheduled nightly integration run (the PDI hibernates —
it would need a keep-alive), `persist-credentials: false` on checkouts.
