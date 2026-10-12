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

Skills for your own organisation or domain belong in your own repository: see [EXTENDING.md](EXTENDING.md). Changes to the five skills shipped here must pass `mcp-server-servicenow --validate-skills src/servicenow_mcp/skills`, cite ServiceNow documentation by link (the [skill profile](docs/skill-profile.md)), and keep the counts in `tests/test_skills.py` current.

## Adding a New Tool

1. Add the function in the appropriate `src/servicenow_mcp/tools/` file
2. Use the `@mcp.tool()` decorator with `Annotated[type, Field()]` parameters
3. Get config/auth from the singleton inside the function body:

```python
from servicenow_mcp.server import mcp, get_config, get_auth_manager

@mcp.tool()
def my_tool(
    param: Annotated[str, Field(description="...")],
) -> dict:
    """Tool description becomes the MCP tool description."""
    config = get_config()
    auth_manager = get_auth_manager()
    # ...
```

4. Add a schema test in `tests/test_tools.py`
5. Update the tool count assertion in `tests/test_registry.py`

## Running Integration Tests

Live tests read credentials from the environment only (use a secret-store launcher rather than a file); refused tools are skipped with the missing grant. Use a least-privilege user, not `admin` (new instances refuse basic auth for it anyway):

```bash
SERVICENOW_INSTANCE_URL=https://your-pdi.service-now.com \
SERVICENOW_USERNAME=mcp.integration SERVICENOW_PASSWORD=... \
python -m pytest tests/integration/ -v

# End-to-end over stdio, both protocol eras (the readonly profile changes nothing)
python scripts/stdio_smoke.py --profile readonly
```

## Code Style

- Python 3.11+, type hints on all functions
- `ruff` for linting
- Follow existing patterns in the codebase

## Releases

Maintainers: see [RELEASING.md](RELEASING.md) for the full release runbook —
publish pipeline, verification gates, and failure recovery.
