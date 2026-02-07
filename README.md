# mcp-server-servicenow

**Phase 1 — Foundation**

A comprehensive MCP (Model Context Protocol) server for ServiceNow. Provides 18 tools for table operations, CMDB management, system queries, and update set management — usable from any MCP client (Claude Desktop, Claude Code, etc.).

## Install

```bash
git clone https://github.com/jschuller/mcp-server-servicenow.git
cd mcp-server-servicenow
pip install -e ".[dev]"
```

## Configuration

Copy `.env.example` to `.env` and fill in your values. OAuth is recommended for production:

```bash
# OAuth (recommended)
SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com
SERVICENOW_AUTH_TYPE=oauth
SERVICENOW_CLIENT_ID=your-client-id
SERVICENOW_CLIENT_SECRET=your-client-secret
SERVICENOW_USERNAME=your-username
SERVICENOW_PASSWORD=your-password
```

Basic auth for development:

```bash
SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com
SERVICENOW_AUTH_TYPE=basic
SERVICENOW_USERNAME=admin
SERVICENOW_PASSWORD=your-password
```

### Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "python",
      "args": ["-m", "servicenow_mcp.cli"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "basic",
        "SERVICENOW_USERNAME": "admin",
        "SERVICENOW_PASSWORD": "your-password"
      }
    }
  }
}
```

## Available Tools

### Table API (5 tools)
| Tool | Description |
|------|-------------|
| `list_records` | List records from any table with filtering, field selection, and pagination |
| `get_record` | Get a single record by sys_id |
| `create_record` | Create a new record in any table |
| `update_record` | Update an existing record |
| `delete_record` | Delete a record by sys_id |

### CMDB (5 tools)
| Tool | Description |
|------|-------------|
| `list_ci` | List configuration items with class and query filtering |
| `get_ci` | Get a single CI by sys_id |
| `create_ci` | Create a new configuration item |
| `update_ci` | Update a configuration item |
| `get_ci_relationships` | Get parent/child relationships for a CI |

### System (3 tools)
| Tool | Description |
|------|-------------|
| `get_system_properties` | Query system properties |
| `get_current_user` | Get authenticated user info |
| `get_table_schema` | Get table data dictionary (field definitions) |

### Update Sets (5 tools)
| Tool | Description |
|------|-------------|
| `list_update_sets` | List update sets with state filtering |
| `get_update_set` | Get update set details |
| `create_update_set` | Create a new update set |
| `set_current_update_set` | Set the active update set |
| `list_update_set_changes` | List changes within an update set |

## Architecture

```
src/servicenow_mcp/
├── cli.py                 # Entry point, env var parsing
├── server.py              # MCP server, tool dispatch
├── auth/
│   └── auth_manager.py    # OAuth, basic, API key auth
├── tools/
│   ├── table_tools.py     # Generic table CRUD
│   ├── cmdb_tools.py      # CMDB operations
│   ├── system_tools.py    # System info queries
│   └── update_set_tools.py # Update set management
└── utils/
    ├── config.py           # Pydantic config models
    ├── http.py             # HTTP client with error handling
    └── tool_utils.py       # Tool registry
```

All tools use the low-level MCP SDK with Pydantic parameter validation. HTTP requests go through a centralized client (`utils/http.py`) with structured error handling and OAuth token auto-refresh on 401.

## Development

```bash
# Run tests
python -m pytest tests/ -v

# Lint
ruff check src/ tests/

# Run server locally
python -m servicenow_mcp.cli
```

## Roadmap

- **Phase 1** (current): Foundation — git, tests, OAuth retry, documentation
- **Phase 2**: Migrate to standalone FastMCP v2.x with decorator-based tools
- **Phase 3**: Add MCP Resources and Prompts (incident triage, change drafting, etc.)
- **Phase 4**: PyPI distribution as `mcp-server-servicenow`, MCP Registry listing

## License

MIT
