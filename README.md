# mcp-server-servicenow

![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)
![FastMCP](https://img.shields.io/badge/FastMCP-3.0-green.svg)
![MCP Protocol](https://img.shields.io/badge/MCP-2025--11--25-purple.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![18 Tools](https://img.shields.io/badge/tools-18-orange.svg)

<!-- mcp-name: io.github.jschuller/mcp-server-servicenow -->

Connect Claude AI to ServiceNow. 18 MCP tools for incidents, CMDB, update sets, and more — accessible from Claude Desktop, Claude Code, or any MCP client over stdio or Streamable HTTP.

## What This Does

This MCP server lets AI assistants interact directly with a ServiceNow instance. Instead of copy-pasting between ServiceNow and your AI tool, Claude can query incidents, create records, explore CMDB relationships, and manage update sets through natural conversation.

Built with [FastMCP 3.0](https://gofastmcp.com) for decorator-based tool definitions and dual transport support.

## Native vs Community

ServiceNow shipped a native MCP Server in Zurich (2025). Here's when to use each:

| | Native (Zurich+) | This project |
|---|---|---|
| **SN version** | Zurich+ only | Any version (Tokyo+) |
| **Entitlement** | Requires Now Assist SKU | None (MIT, free) |
| **Auth model** | OAuth 2.1 + PKCE via AI Control Tower | OAuth 2.1 + PKCE via FastMCP proxy |
| **Governance** | AI Control Tower policies | Self-managed |
| **Table access** | Governed by CT config | Full table API access |
| **AI models** | Now Assist models + approved | Any MCP client (Claude, GPT, etc.) |
| **Custom tools** | Requires SN development | Python — add tools in minutes |

**Use native** if you're on Zurich+ with Now Assist and need AI Control Tower governance.
**Use this** if you're on an older version, don't have the entitlement, need custom table access, or want to use any AI model.

## Getting Started

### 1. Get a ServiceNow Instance

Sign up for a free [Personal Developer Instance (PDI)](https://developer.servicenow.com/) — it comes pre-loaded with demo data. Wake it from the developer portal if it's hibernating.

### 2. Install

```bash
# From PyPI (recommended)
pip install mcp-server-servicenow

# Or run directly with uvx (no install needed)
uvx mcp-server-servicenow --help
```

### 3. Configure Your MCP Client

Copy `.mcp.json.example` to `.mcp.json` and fill in your credentials, or use the Claude Code CLI:

```bash
claude mcp add servicenow -- uvx mcp-server-servicenow \
  --instance-url https://your-instance.service-now.com \
  --auth-type basic --username admin --password your-password
```

### 4. Verify

Ask Claude: "List the 5 most recent incidents" — if it returns data, you're connected.

### From Source

```bash
git clone https://github.com/jschuller/mcp-server-servicenow.git
cd mcp-server-servicenow
pip install -e .

# Run with stdio (Claude Desktop / Claude Code)
mcp-server-servicenow \
  --instance-url https://your-instance.service-now.com \
  --auth-type basic \
  --username admin \
  --password your-password

# Or run with HTTP (remote access / Cloud Run)
mcp-server-servicenow \
  --transport streamable-http \
  --port 8080 \
  --instance-url https://your-instance.service-now.com \
  --auth-type basic \
  --username admin \
  --password your-password
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

## Configuration Examples

Copy `.mcp.json.example` to `.mcp.json` and fill in your credentials. The JSON format is the same for Claude Code (`.mcp.json`) and Claude Desktop (`claude_desktop_config.json`).

### Basic Auth (stdio)

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": ["mcp-server-servicenow"],
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

### OAuth Password Grant (stdio)

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": ["mcp-server-servicenow"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://your-instance.service-now.com",
        "SERVICENOW_AUTH_TYPE": "oauth",
        "SERVICENOW_CLIENT_ID": "your-client-id",
        "SERVICENOW_CLIENT_SECRET": "your-client-secret",
        "SERVICENOW_USERNAME": "admin",
        "SERVICENOW_PASSWORD": "your-password"
      }
    }
  }
}
```

### Multiple Instances

```json
{
  "mcpServers": {
    "servicenow-dev": {
      "command": "uvx",
      "args": ["mcp-server-servicenow"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://dev12345.service-now.com",
        "SERVICENOW_AUTH_TYPE": "basic",
        "SERVICENOW_USERNAME": "admin",
        "SERVICENOW_PASSWORD": "dev-password"
      }
    },
    "servicenow-prod": {
      "command": "uvx",
      "args": ["mcp-server-servicenow"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://prod12345.service-now.com",
        "SERVICENOW_AUTH_TYPE": "oauth",
        "SERVICENOW_CLIENT_ID": "prod-client-id",
        "SERVICENOW_CLIENT_SECRET": "prod-client-secret",
        "SERVICENOW_USERNAME": "svc-account",
        "SERVICENOW_PASSWORD": "prod-password"
      }
    }
  }
}
```

## Deployment

### Docker / Cloud Run

```bash
# Build
docker build -t mcp-server-servicenow .

# Run locally
docker run -p 8080:8080 \
  -e SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com \
  -e SERVICENOW_AUTH_TYPE=basic \
  -e SERVICENOW_USERNAME=admin \
  -e SERVICENOW_PASSWORD=your-password \
  mcp-server-servicenow

# Deploy to Cloud Run with global creds (requires GCP IAM for access)
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

# Deploy to Cloud Run with OAuth (per-user auth, publicly accessible)
gcloud run deploy servicenow-mcp \
  --source . \
  --region us-east1 \
  --port 8080 \
  --allow-unauthenticated \
  --set-env-vars "SERVICENOW_INSTANCE_URL=..." \
  --set-env-vars "MCP_OAUTH_CLIENT_ID=..." \
  --set-env-vars "MCP_OAUTH_CLIENT_SECRET=..." \
  --set-env-vars "MCP_BASE_URL=https://servicenow-mcp-xxxxx.run.app" \
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

## Security Model

Three deployment modes with increasing security:

| Mode | MCP Endpoint Auth | SN Backend Auth | Use Case |
|------|------------------|-----------------|----------|
| **stdio** | None (local process) | Global creds (env vars) | Claude Desktop, Claude Code |
| **HTTP (open)** | None | Global creds (env vars) | Development, testing |
| **HTTP + OAuth** | OAuth 2.1 + PKCE | Per-user SN token | Production, Cloud Run |

### OAuth 2.1 + PKCE (recommended for production)

When deployed with OAuth, each user authenticates with their own ServiceNow credentials. The server acts as an OAuth proxy: it handles DCR and consent locally, redirects users to ServiceNow for login, then exchanges the auth code for SN tokens server-side.

**Defense in depth:** OAuth 2.1 + PKCE on the MCP endpoint, per-user SN ACLs on every API call, encrypted token storage, CSRF-protected consent screen.

**Setup:**

1. In ServiceNow, go to **System OAuth > Application Registry** and create an OAuth API endpoint for external clients
2. Set the redirect URI to `{your-server-url}/auth/callback`
3. Deploy with OAuth env vars:

```bash
SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com
MCP_OAUTH_CLIENT_ID=<from Application Registry>
MCP_OAUTH_CLIENT_SECRET=<from Application Registry>
MCP_BASE_URL=https://your-mcp-server.run.app
MCP_TRANSPORT=streamable-http
```

4. In Claude.ai, add the server URL as an MCP connector — the OAuth flow handles the rest

**Requires:** ServiceNow San Diego+ (2022) for PKCE support.

## Configuration Reference

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
| `SERVICENOW_API_KEY_HEADER` | `--api-key-header` | API key header name (default: X-ServiceNow-API-Key) |
| `MCP_TRANSPORT` | `--transport` | `stdio` (default) or `streamable-http` |
| `PORT` | `--port` | HTTP port (default: 8080) |
| `MCP_OAUTH_CLIENT_ID` | `--mcp-oauth-client-id` | SN OAuth app client ID for MCP endpoint auth |
| `MCP_OAUTH_CLIENT_SECRET` | `--mcp-oauth-client-secret` | SN OAuth app client secret for MCP endpoint auth |
| `MCP_BASE_URL` | `--mcp-base-url` | Public URL of this MCP server |

## Troubleshooting

### Instance is hibernating
PDIs hibernate after inactivity. Wake it at [developer.servicenow.com](https://developer.servicenow.com) — click your instance and select "Wake Up". You'll get HTML login pages instead of JSON until it's awake.

### 401 Unauthorized
- **Basic auth:** Verify username/password are correct; check that the user has the `rest_api_explorer` or `admin` role
- **OAuth:** Ensure the OAuth Application Registry entry is active and the redirect URI matches. Try regenerating the client secret
- **Expired token:** OAuth tokens expire; the server retries once automatically, but if both attempts fail, check your credentials

### OAuth `get_current_user` returns different fields
With OAuth bearer tokens, `get_current_user` uses a Table API fallback (the UI endpoint requires session auth). The response fields are the same but sourced from `sys_user` instead of the UI API.

### CLI TypeError on stdio transport
Fixed in v0.3.1. If you see `TypeError: unexpected keyword argument 'host'`, upgrade: `pip install --upgrade mcp-server-servicenow`.

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
- **Phase 3** &#x2705; Security — OAuth 2.1 + PKCE proxy, per-user SN auth, matches native Zurich model
- **Phase 4** &#x1F51C; Skills & workflows — CMDB Data Foundations, incident triage, change management
- **Phase 5** &#x1F6A7; Distribution — PyPI package, MCP Registry listing, Claude Code skills

## License

[MIT](LICENSE)
