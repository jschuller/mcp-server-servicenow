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
python -m pytest tests/ -v
ruff check src/ tests/
```

4. Open a pull request

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

Integration tests require a ServiceNow PDI:

```bash
export SERVICENOW_INSTANCE_URL=https://your-pdi.service-now.com
export SERVICENOW_USERNAME=admin
export SERVICENOW_PASSWORD=your-password

python -m pytest tests/integration/ -v
```

## Code Style

- Python 3.11+, type hints on all functions
- `ruff` for linting
- Follow existing patterns in the codebase
