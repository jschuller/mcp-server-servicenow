# Configuration Guide

## Configuration Examples

Copy `.mcp.json.example` to `.mcp.json` and fill in your credentials. The JSON format is the same for Claude Code (`.mcp.json`) and Claude Desktop (`claude_desktop_config.json`).

### Basic Auth (stdio)

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": ["--prerelease", "allow", "mcp-server-servicenow"],
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
      "args": ["--prerelease", "allow", "mcp-server-servicenow"],
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
      "args": ["--prerelease", "allow", "mcp-server-servicenow"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://dev12345.service-now.com",
        "SERVICENOW_AUTH_TYPE": "basic",
        "SERVICENOW_USERNAME": "admin",
        "SERVICENOW_PASSWORD": "dev-password"
      }
    },
    "servicenow-prod": {
      "command": "uvx",
      "args": ["--prerelease", "allow", "mcp-server-servicenow"],
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
| `MCP_HOST` | `--host` | HTTP bind address (default: `127.0.0.1`; set `0.0.0.0` to listen on all interfaces) |
| `PORT` | `--port` | HTTP port (default: 8080) |
| `MCP_STATIC_TOKENS` | `--mcp-static-tokens` | Comma-separated static bearer tokens for MCP endpoint auth (CI/CD) |
| `MCP_OAUTH_CLIENT_ID` | `--mcp-oauth-client-id` | SN OAuth app client ID for MCP endpoint auth |
| `MCP_OAUTH_CLIENT_SECRET` | `--mcp-oauth-client-secret` | SN OAuth app client secret for MCP endpoint auth |
| `MCP_BASE_URL` | `--mcp-base-url` | Public URL of this MCP server |
