# Configuration Guide

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
        "SERVICENOW_USERNAME": "mcp.integration",
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
        "SERVICENOW_USERNAME": "mcp.integration",
        "SERVICENOW_PASSWORD": "your-password"
      }
    }
  }
}
```

### Read-only with a table denylist (stdio)

```json
{
  "mcpServers": {
    "servicenow-prod-ro": {
      "command": "uvx",
      "args": ["mcp-server-servicenow", "--read-only"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://prod12345.service-now.com",
        "SERVICENOW_AUTH_TYPE": "basic",
        "SERVICENOW_USERNAME": "svc-readonly",
        "SERVICENOW_PASSWORD": "prod-password",
        "SERVICENOW_TABLE_DENYLIST": "sys_user*,sys_user_has_role,oauth_*",
        "SERVICENOW_AUDIT_LOG": "/var/log/servicenow-mcp/audit.jsonl"
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
        "SERVICENOW_USERNAME": "mcp.integration",
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

### Keeping secrets out of config files

Every client below accepts a launcher command, so the password or key can come from your OS secret store at start-up instead of sitting in JSON or TOML. The pattern is `<launcher> VAR=<secret-name> -- uvx mcp-server-servicenow …` — for example a small script that runs `security find-generic-password` (macOS Keychain) or `secret-tool lookup` (Linux) and `exec`s the server with the value in its environment. Claude Desktop does not expand `${VAR}`, so it needs a launcher; Claude Code, Codex (`env_vars = ["SERVICENOW_PASSWORD"]`) and pi (`"${SERVICENOW_PASSWORD}"`) can also forward a variable from the parent shell.

### Codex CLI (`~/.codex/config.toml`)

```toml
[mcp_servers.servicenow]
command = "uvx"
args = ["mcp-server-servicenow", "--read-only"]
env = { SERVICENOW_INSTANCE_URL = "https://your-instance.service-now.com", SERVICENOW_AUTH_TYPE = "basic", SERVICENOW_USERNAME = "svc.mcp" }
env_vars = ["SERVICENOW_PASSWORD"]   # forwarded from the shell that starts codex
```

### pi (`~/.pi/agent/mcp.json`, or `.pi/mcp.json` per project)

Written by `pi mcp add servicenow --exposure direct --env … -- uvx mcp-server-servicenow --read-only`; check it with `pi mcp list`. Use `"exposure": "direct"` so the model calls the tools by name.

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
| `SERVICENOW_TOKEN_URL` | `--token-url` | OAuth token URL (default: `<instance>/oauth_token.do`) |
| `SERVICENOW_TIMEOUT` | `--timeout` | HTTP timeout in seconds (default: 30) |
| `SERVICENOW_DEBUG` | `--debug` | Debug logging (`true`/`false`) |
| `MCP_TRANSPORT` | `--transport` | `stdio` (default) or `streamable-http` |
| `MCP_HOST` | `--host` | HTTP bind address (default: `127.0.0.1`; set `0.0.0.0` to listen on all interfaces) |
| `PORT` | `--port` | HTTP port (default: 8080) |
| `MCP_STATIC_TOKENS` | `--mcp-static-tokens` | Comma-separated static bearer tokens for MCP endpoint auth (CI/CD) |
| `MCP_OAUTH_CLIENT_ID` | `--mcp-oauth-client-id` | SN OAuth app client ID for MCP endpoint auth |
| `MCP_OAUTH_CLIENT_SECRET` | `--mcp-oauth-client-secret` | SN OAuth app client secret for MCP endpoint auth |
| `MCP_BASE_URL` | `--mcp-base-url` | Public URL of this MCP server |

### Safety rails

| Variable | CLI Arg | Description |
|----------|---------|-------------|
| `SERVICENOW_READ_ONLY` | `--read-only` | Hide the 7 write tools and refuse non-GET requests (default: off) |
| `SERVICENOW_TABLE_ALLOWLIST` | `--table-allowlist` | Comma-separated tables/globs that may be accessed (empty = all) |
| `SERVICENOW_TABLE_DENYLIST` | `--table-denylist` | Comma-separated tables/globs that may never be accessed; wins over the allowlist |
| `SERVICENOW_ALLOW_JS_QUERIES` | `--allow-js-queries` | Permit arbitrary `javascript:` in caller queries (default: only `gs.*` date helpers) |
| `SERVICENOW_WRITE_CONFIRM` | `--write-confirm` | Ask the user to confirm `update_record` / `update_ci` / `delete_record` via MCP elicitation (default: off) |
| `SERVICENOW_AUDIT_LOG` | `--audit-log` | `stderr` (default), `off`, or a file path for the JSON audit log |

Boolean env vars accept `1`, `true`, `yes`, `on` (case-insensitive). Empty values and unexpanded `${VAR}` placeholders (as Claude Code passes for unset plugin env vars) are treated as unset.
