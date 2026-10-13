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
   `CHANGELOG.md` section (`## [X.Y.Z] - YYYY-MM-DD`).

   The template pins the release too, and CI checks the pins. The places are:
   - `examples/template/.claude-plugin/plugin.json` (`mcp-server-servicenow==X.Y.Z`);
   - `examples/template/.github/workflows/validate-skills.yml` (`@vX.Y.Z` and
     `server-version`);
   - `examples/template/.github/workflows/evals.yml` (`SERVER_VERSION`);
   - the template README.

   After tool changes, refresh the eval mocks. CI's strict wrapper check fails on a
   stale `_tools.json`. Run `--eval-mocks` on `.` and on each `examples/*` plugin.
   After the release, update the template repository (post-release step 5).

2. **Verification gates** — all of these, no skips:

   ```sh
   uv run ruff check src/ tests/
   uv run ruff format --check src/ tests/
   uv run mypy
   uv run pytest tests/ --ignore=tests/integration     # unit suite
   uv run --with build python -m build
   uv run --with 'twine>=7' twine check --strict dist/*   # Metadata-Version 2.5
   curl -sfL "$(jq -r '."$schema"' server.json)" -o /tmp/server.schema.json
   uv run --with jsonschema python -c 'import json, jsonschema; jsonschema.validate(json.load(open("server.json")), json.load(open("/tmp/server.schema.json")))'
   uv run pytest tests/integration/ -v                 # live E2E (below)
   ```

   The `server.json` check catches what the registry would reject on release
   day, such as a description over 100 characters.

   The live checks read credentials from the environment only — start them
   under a secret-store launcher, never from a file:

   ```sh
   with-secrets SERVICENOW_API_KEY=svc/homelab/servicenow-<pdi>-apikey -- env \
     SERVICENOW_INSTANCE_URL=https://<pdi>.service-now.com \
     SERVICENOW_AUTH_TYPE=api_key \
     sh -c 'uv run pytest tests/integration/ -v -rs && uv run python scripts/stdio_smoke.py --profile readonly && uv run mcp-server-servicenow --check'
   ```

   The `itil` + `snc_read_only` key must list 12 tools with no flag, and
   `--check` must exit 0 (record, schema and aggregate show as limits under
   an API key). Repeat the smoke and `--check` with an OAuth
   client-credentials identity (`SERVICENOW_AUTH_TYPE=oauth`,
   `SERVICENOW_CLIENT_ID`, the secret from the store, `SERVICENOW_USERNAME=`
   and `SERVICENOW_PASSWORD=` blank so a local `.env` can't turn it into the
   password grant), and `--check` with the instance URL as `devNNNNNN`, with
   a trailing slash and as a pasted UI URL: all must reach the instance.
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
   - Claude Code: `claude mcp add servicenow-dev -- uv run --directory . mcp-server-servicenow …`
     with the start-here identity and no flag must list 12 tools; with a
     writable identity, update a scratch incident — Claude Code's permission
     prompt must appear before the write tool runs.
   - Claude Desktop: point `claude_desktop_config.json` at the local build;
     a read and a scratch update work.
   - Plugin: `claude --plugin-dir .` with only `SERVICENOW_INSTANCE_URL/USERNAME/PASSWORD`
     set must start (the `${VAR:-default}` passthrough check).
   - the four `skill://…/SKILL.md` resources list and read (Claude Code `/mcp` → resources).
   - Run Claude Code as `command claude …` if your shell aliases `claude`
     (e.g. to `--dangerously-skip-permissions`), or the permission checks
     are skipped.
   - Codex: `codex mcp add … -- uv run --directory . mcp-server-servicenow`,
     then `codex exec` a read question — read-only tools run without approval,
     a skill is readable via `read_mcp_resource`, a write tool is refused by
     `codex exec`; in the TUI a write tool shows Codex's approval prompt.
   - pi (1.0+): `pi mcp add … --exposure direct -- uv run --directory . mcp-server-servicenow`,
     `pi mcp list` must report 12/19 tools and 18 resources.
   - Behaviour evals (Claude Code only, mocked tools, no instance):
     `command claude plugin eval . --trust-plugin --runs 1 --ablation none --model sonnet --no-publish --max-cost-usd 5`.
     Runs draw on the signed-in plan's usage. Hitting a usage limit mid-suite scores
     the rest 0, so read the `NOTES` column before treating a low score as a
     regression (`--eval-summary` refuses such a run). Not a gate yet: the owner
     decides the suite's size and cadence.

4. Push to main and wait for CI green — the test matrix (3.11–3.14)
   plus the `package` job (version consistency, `uv lock --check`,
   build + twine).

   Land the reviewed commits on main unchanged: fast-forward main to the PR branch
   (`git push origin <branch>:main` once the PR's CI is green), not GitHub's
   rebase-merge, which rewrites every commit. The examples' `RESULTS.md` files name the
   commit their run came from, and a rewritten commit leaves that link dangling.

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
   `uvx --no-cache mcp-server-servicenow==X.Y.Z --help`. For a few minutes after
   publishing, PyPI's CDN can still answer that the version doesn't exist (v0.9.0:
   about 5 minutes); wait and retry.
5. Template repository ([jschuller/servicenow-skills-template](https://github.com/jschuller/servicenow-skills-template)):
   replace its files with the tagged `examples/template/`, commit, tag `vX.Y.Z` and push.
   Its "Validate skills" run then exercises the released Action and package, and must
   pass.

   ```sh
   git archive vX.Y.Z examples/template | tar -x -C /tmp/tpl   # copy /tmp/tpl/examples/template/ over a clone
   ```

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
