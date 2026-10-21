# Contributing

Thanks for your interest in contributing to mcp-server-servicenow!

## Getting Started

```bash
git clone https://github.com/jschuller/mcp-server-servicenow.git
cd mcp-server-servicenow
pip install -e ".[dev]"
```

## Development Workflow

1. Create a branch from `main`
2. Make your changes
3. Run tests and lint:

```bash
python -m pytest tests/ -v --ignore=tests/integration
ruff check src/ tests/
mypy src/
```

4. Open a pull request

## Skills

Skills for your own organisation or domain belong in your own repository: see [EXTENDING.md](EXTENDING.md). Changes to the four skills shipped here must pass `mcp-server-servicenow --validate-skills src/servicenow_mcp/skills`, cite ServiceNow documentation by link (the [skill profile](docs/skill-profile.md)), and keep the counts in `tests/test_skills.py` and the wheel check in `.github/workflows/ci.yml` current.

## Adding a New Tool

1. Add the function in the appropriate `src/servicenow_mcp/tools/` file
2. Use the `@mcp.tool()` decorator with `Annotated[type, Field()]` parameters
3. Get config/auth from the singleton inside the function body:

```python
from servicenow_mcp.server import mcp, get_config, get_auth_manager
from servicenow_mcp.tools import annotations

@mcp.tool(tags={"read", "table"}, annotations=annotations.READ)
def my_tool(
    param: Annotated[str, Field(description="...")],
) -> dict:
    """Tool description becomes the MCP tool description."""
    config = get_config()
    auth_manager = get_auth_manager()
    # ...
```

4. Tag it `read` or `write`, give it the matching preset from `tools/annotations.py` (`tests/test_annotations.py` checks every tool), and add its name to `READ_TOOLS` or `WRITE_TOOLS` in `tests/inventory.py`; every test that counts tools, and `scripts/stdio_smoke.py`, reads that list
5. A tool that returns a list envelope: give it a `TypedDict` return type in `tools/results.py` and an entry in `LIST_KEYS`, or the response limiter hides its `outputSchema`
6. A new argument that names a table, field or record goes in `IDENTIFIER_ARGS` (or the field-list or query lists) in `middleware/policy.py`, so the policy middleware validates it; a tool that always reads one table goes in `FIXED_TABLES` there, so the audit log records that table
7. Add a schema test in `tests/test_tools.py`
8. Update the counts in prose (`grep -rnE "[0-9]+ (read-only |write )?tools" README.md docs RELEASING.md .github src/servicenow_mcp/__init__.py scripts`), the tables in `README.md` and `docs/tools.md`, and the roles table in `docs/tools.md`
9. Refresh the eval mocks: `mcp-server-servicenow --eval-mocks .` and each `examples/*` plugin (CI fails on a stale `_tools.json`)

## Running Integration Tests

Live tests read credentials from the environment only (use a secret-store launcher rather than a file); refused tools are skipped with the missing grant. Use a least-privilege user, not `admin` (new instances refuse basic auth for it anyway):

```bash
SERVICENOW_INSTANCE_URL=https://your-pdi.service-now.com \
SERVICENOW_USERNAME=mcp.integration SERVICENOW_PASSWORD=... \
python -m pytest tests/integration/ -v

# End-to-end over stdio, both protocol eras (the readonly profile changes nothing)
python scripts/stdio_smoke.py --profile readonly --expect-tools 13
```

Which identities to test with, how many tools each should list and which refusals to expect: [docs/testing.md](docs/testing.md).

## Code Style

- Python 3.11+, type hints on all functions
- `ruff check src/ tests/` and `ruff format --check src/ tests/` (CI runs both)
- Follow existing patterns in the codebase

## Releases

Maintainers: see [RELEASING.md](RELEASING.md) for the full release runbook —
publish pipeline, verification gates, and failure recovery.
