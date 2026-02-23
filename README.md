# mcp-server-servicenow

![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)
![FastMCP](https://img.shields.io/badge/FastMCP-3.0-green.svg)
![MCP Protocol](https://img.shields.io/badge/MCP-2025--11--25-purple.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![18 Tools](https://img.shields.io/badge/tools-18-orange.svg)

Connect Claude AI to ServiceNow. 18 MCP tools for incidents, CMDB, update sets, and more — accessible from Claude Desktop, Claude Code, or any MCP client over stdio or Streamable HTTP.

## What This Does

This MCP server lets AI assistants interact directly with a ServiceNow instance. Instead of copy-pasting between ServiceNow and your AI tool, Claude can query incidents, create records, explore CMDB relationships, and manage update sets through natural conversation.

Built with [FastMCP 3.0](https://gofastmcp.com) for decorator-based tool definitions and dual transport support.

## Quick Start

```bash
# Clone and install
git clone https://github.com/jschuller/mcp-server-servicenow.git
cd mcp-server-servicenow
pip install -e .

# Run with stdio (Claude Desktop / Claude Code)
mcp-servicenow \
  --instance-url https://your-instance.service-now.com \
  --auth-type basic \
  --username admin \
  --password your-password

# Or run with HTTP (remote access / Cloud Run)
mcp-servicenow \
  --transport streamable-http \
  --port 8080 \
  --instance-url https://your-instance.service-now.com \
  --auth-type basic \
  --username admin \
  --password your-password
```

### Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "mcp-servicenow",
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

### Claude Code

```bash
claude mcp add servicenow -- mcp-servicenow \
  --instance-url https://your-instance.service-now.com \
  --auth-type basic --username admin --password your-password
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
Claude / MCP Client
       │
       │  stdio or Streamable HTTP
       ▼
┌─────────────────────────┐
│   FastMCP 3.0 Server    │
│   (server.py)           │
├─────────────────────────┤
│  @mcp.tool() decorators │
│  ┌───────────────────┐  │
│  │ table_tools (5)   │  │
│  │ cmdb_tools  (5)   │  │
│  │ system_tools (3)  │  │
│  │ update_set_tools(5)│  │
│  └───────────────────┘  │
├─────────────────────────┤
│  auth_manager + http.py │
└────────────┬────────────┘
             │  REST API
             ▼
     ServiceNow Instance
      /api/now/table/*
```

## Deployment

### Docker / Cloud Run

```bash
# Build
docker build -t mcp-servicenow .

# Run locally
docker run -p 8080:8080 \
  -e SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com \
  -e SERVICENOW_AUTH_TYPE=basic \
  -e SERVICENOW_USERNAME=admin \
  -e SERVICENOW_PASSWORD=your-password \
  mcp-servicenow

# Deploy to Cloud Run (requires GCP authentication)
gcloud run deploy servicenow-mcp \
  --source . \
  --region us-east1 \
  --port 8080 \
  --no-allow-unauthenticated \
  --set-env-vars "SERVICENOW_INSTANCE_URL=..." \
  --set-env-vars "SERVICENOW_AUTH_TYPE=basic" \
  --set-env-vars "SERVICENOW_USERNAME=..." \
  --set-env-vars "SERVICENOW_PASSWORD=..." \
  --set-env-vars "MCP_TRANSPORT=streamable-http"
```

### Verify HTTP Transport

```bash
# Local testing
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}},"id":1}'

# Cloud Run (requires GCP auth token)
curl -X POST https://your-service-url.run.app/mcp \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}},"id":1}'
```

## Configuration

All settings can be passed as CLI args or environment variables. See `.env.example`.

| Variable | CLI Arg | Description |
|----------|---------|-------------|
| `SERVICENOW_INSTANCE_URL` | `--instance-url` | ServiceNow instance URL |
| `SERVICENOW_AUTH_TYPE` | `--auth-type` | `basic`, `oauth`, or `api_key` |
| `SERVICENOW_USERNAME` | `--username` | Username for basic/OAuth auth |
| `SERVICENOW_PASSWORD` | `--password` | Password for basic/OAuth auth |
| `SERVICENOW_CLIENT_ID` | `--client-id` | OAuth client ID |
| `SERVICENOW_CLIENT_SECRET` | `--client-secret` | OAuth client secret |
| `SERVICENOW_API_KEY` | `--api-key` | API key for api_key auth |
| `MCP_TRANSPORT` | `--transport` | `stdio` (default) or `streamable-http` |
| `PORT` | `--port` | HTTP port (default: 8080) |

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run unit tests
python -m pytest tests/ -v --ignore=tests/integration

# Run integration tests (requires PDI credentials)
SERVICENOW_INSTANCE_URL=https://your-pdi.service-now.com \
SERVICENOW_USERNAME=admin \
SERVICENOW_PASSWORD=your-password \
python -m pytest tests/integration/ -v

# Lint
ruff check src/ tests/
```

## Roadmap

- **Phase 1** &#x2705; Foundation — 18 tools, OAuth retry, structured error handling
- **Phase 2** &#x2705; Remote access — FastMCP 3.0, Streamable HTTP, Cloud Run deployment
- **Phase 3** &#x1F51C; AI workflows — incident triage prompts, change drafting templates, CMDB exploration resources
- **Phase 4** &#x1F51C; Distribution — PyPI package, MCP Registry listing, one-click install

## License

[MIT](LICENSE)
