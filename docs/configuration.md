# Configuration Guide

## Recommended integration identity

How to set up the ServiceNow user this server signs in as, following ServiceNow's [Security Best Practices Guide](https://www.servicenow.com/content/dam/servicenow-assets/public/en-us/doc-type/resource-center/white-paper/instance-security-best-practice.pdf) (release Australia, 2026-09-18). Page numbers refer to that guide.

- **One dedicated machine user per integration**, flagged *Web service access only*, so it cannot sign in to the UI and every action in the audit trail traces back to this integration (pp. 15, 18, 28). The start-here `mcp.integration` user is one; on a company instance ask your admin for one per team or pipeline rather than sharing a person's account.
- **Tokens over long-lived passwords** (p. 29). Use [OAuth client credentials](#oauth-client-credentials-headless) for headless and CI use, and the per-user [OAuth 2.1 + PKCE proxy](deployment.md#oauth-21--pkce-recommended-for-production) when people should act with their own permissions. Basic auth is fine on a developer instance; the OAuth password grant is legacy because it skips MFA.
- **Least privilege.** `itil` + `snc_read_only` reads incidents, changes, problems, SLAs and the CMDB, and can't change anything; add only the roles your tools need ([roles](tools.md#roles)). `snc_read_only` blocks writes whatever other roles the user has, and the server then hides its write tools. Never give the integration user `admin` outside a developer instance.
- **Scope tables and APIs on the instance.** ACLs, Machine Identity access controls and REST API access policies limit what the identity can reach even where its roles would allow more (pp. 17, 37). ServiceNow enforces these for every client, dot-walked fields included, so this is where to keep an integration away from HR, security or user data.
- **Keep secrets out of logs and files** (p. 30). The audit log records the names of written fields, never their values, but it does log encoded queries (secret-like values masked), which can hold filter values; give the server its credentials through the environment or a [launcher](#keeping-secrets-out-of-config-files) that reads your OS secret store.

One thing to know when you grant `itil`: on a base instance it can read every user's role assignments (`sys_user_has_role`), including who holds `admin`. The server uses that table only for the caller's own rows, but the data is there for any `itil` user; tighten that table's read ACL if it matters on your instance.

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
        "SERVICENOW_PASSWORD": "<from your secret store: see below>"
      }
    }
  }
}
```

### OAuth client credentials (headless)

No username or password: the server uses the client credentials grant, and every call runs as the OAuth client's application user. This suits CI, scheduled jobs and instances that sign people in through SSO only.

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
        "SERVICENOW_CLIENT_SECRET": "<from your secret store: see below>"
      }
    }
  }
}
```

An admin sets up the instance once:

1. Create the system property `glide.oauth.inbound.client.credential.grant_type.enabled` with the value `true`; it is off by default ([Client credentials](https://www.servicenow.com/docs/r/brazil/platform-security/authentication/client-credentials.html)).
2. Create the OAuth client (Machine Identity Console > Inbound integrations > New integration > [Client credentials grant](https://www.servicenow.com/docs/r/brazil/platform-security/authentication/client-credential-grant.html), or the Application Registry) and set its **OAuth Application User** ([how](https://www.servicenow.com/docs/r/brazil/platform-security/authentication/add-oauth-application-user.html)) to a dedicated integration user: Web service access only and least privilege, such as `itil` + `snc_read_only` for read-only use. Never System Administrator: the token acts with that user's full rights.
3. Let the token reach the APIs: a broadly scoped client, or an auth scope or REST API access policy covering the Table API (and the Aggregate API for `aggregate_records`).

Tokens last 30 minutes and come without a refresh token; the server requests a new one when a call returns 401. Audit lines name the identity as `oauth-client:<client_id>`. If both `SERVICENOW_USERNAME` and `SERVICENOW_PASSWORD` are set the server uses the password grant instead; setting only one is a startup error.

Write tools are hidden for an `snc_read_only` identity only when it can read its own role rows: `itil` can, an identity with `snc_read_only` alone cannot (403 on `sys_user_has_role`), so give that one `--read-only` as well.

### OAuth password grant (legacy, stdio)

The password grant sends a user's password to the token endpoint and skips MFA. Prefer client credentials above, or the per-user OAuth 2.1 + PKCE proxy for shared servers ([deployment.md](deployment.md#oauth-21--pkce-recommended-for-production)).

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
        "SERVICENOW_CLIENT_SECRET": "<from your secret store: see below>",
        "SERVICENOW_USERNAME": "mcp.integration",
        "SERVICENOW_PASSWORD": "<from your secret store: see below>"
      }
    }
  }
}
```

### Read-only (stdio)

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
        "SERVICENOW_PASSWORD": "<from your secret store: see below>",
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
        "SERVICENOW_PASSWORD": "<from your secret store: see below>"
      }
    },
    "servicenow-prod": {
      "command": "uvx",
      "args": ["mcp-server-servicenow"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://prod12345.service-now.com",
        "SERVICENOW_AUTH_TYPE": "oauth",
        "SERVICENOW_CLIENT_ID": "prod-client-id",
        "SERVICENOW_CLIENT_SECRET": "<from your secret store: see below>",
        "SERVICENOW_USERNAME": "svc-account",
        "SERVICENOW_PASSWORD": "<from your secret store: see below>"
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
args = ["mcp-server-servicenow"]
env = { SERVICENOW_INSTANCE_URL = "https://your-instance.service-now.com", SERVICENOW_AUTH_TYPE = "basic", SERVICENOW_USERNAME = "mcp.integration" }
env_vars = ["SERVICENOW_PASSWORD"]   # forwarded from the shell that starts codex
```

### pi (`~/.pi/agent/mcp.json`, or `.pi/mcp.json` per project)

Written by `pi mcp add servicenow --exposure direct --env … -- uvx mcp-server-servicenow`; check it with `pi mcp list`. pi has no approval prompts, so add `--read-only` if the identity can write. Use `"exposure": "direct"` so the model calls the tools by name.

## Configuration Reference

All settings can be passed as CLI args or environment variables. See `.env.example`.

| Variable | CLI Arg | Description |
|----------|---------|-------------|
| `SERVICENOW_INSTANCE_URL` | `--instance-url` | ServiceNow instance URL |
| `SERVICENOW_AUTH_TYPE` | `--auth-type` | `basic`, `oauth`, or `api_key` |
| `SERVICENOW_USERNAME` | `--username` | Username for basic auth or the OAuth password grant (omit for OAuth client credentials) |
| `SERVICENOW_PASSWORD` | `--password` | Password for basic auth or the OAuth password grant (omit for OAuth client credentials) |
| `SERVICENOW_CLIENT_ID` | `--client-id` | OAuth client ID |
| `SERVICENOW_CLIENT_SECRET` | `--client-secret` | OAuth client secret |
| `SERVICENOW_API_KEY` | `--api-key` | API key for api_key auth |
| `SERVICENOW_API_KEY_HEADER` | `--api-key-header` | API key header name (default: `x-sn-apikey`, ServiceNow's default auth parameter) |
| `SERVICENOW_TOKEN_URL` | `--token-url` | OAuth token URL (default: `<instance>/oauth_token.do`) |
| `SERVICENOW_TIMEOUT` | `--timeout` | HTTP timeout in seconds (default: 30) |
| `SERVICENOW_DEBUG` | `--debug` | Debug logging (`true`/`false`) |
| `MCP_TRANSPORT` | `--transport` | `stdio` (default) or `streamable-http` |
| `MCP_HOST` | `--host` | HTTP bind address (default: `127.0.0.1`; set `0.0.0.0` to listen on all interfaces) |
| `PORT` | `--port` | HTTP port (default: 8080) |
| `MCP_STATIC_TOKENS` | `--mcp-static-tokens` | Comma-separated static bearer tokens for MCP endpoint auth (CI/CD), each `token` or `name:token`; the name (letters, digits, `.`, `_`, `-`; up to 32) is what the audit log records as `user` (default `static-client-<position>`). A token must not contain `,`, and an unnamed one must not contain `:` (startup warns when an entry has a `:` but no valid name). Under 32 characters logs a warning; a repeated token or name stops startup |
| `MCP_OAUTH_CLIENT_ID` | `--mcp-oauth-client-id` | SN OAuth app client ID for MCP endpoint auth |
| `MCP_OAUTH_CLIENT_SECRET` | `--mcp-oauth-client-secret` | SN OAuth app client secret for MCP endpoint auth |
| `MCP_BASE_URL` | `--mcp-base-url` | Public URL of this MCP server |

Pass secrets as environment variables, not CLI args: `--password`, `--client-secret`, `--api-key`,
`--mcp-static-tokens` and `--mcp-oauth-client-secret` show up in shell history and process listings.

### Safety rails

| Variable | CLI Arg | Description |
|----------|---------|-------------|
| `SERVICENOW_READ_ONLY` | `--read-only` | Hide the 7 write tools and refuse non-GET requests (default: off) |
| `SERVICENOW_ALLOW_JS_QUERIES` | `--allow-js-queries` | Permit arbitrary `javascript:` in caller queries (default: only `gs.*` date helpers) |
| `SERVICENOW_AUDIT_LOG` | `--audit-log` | `stderr` (default), `off`, or a file path for the JSON audit log |

### Skills

| Variable | CLI Arg | Description |
|----------|---------|-------------|
| `SERVICENOW_SKILLS` | `--skills` | `on` (default) or `off`. `off` serves no `skill://` resources and no `servicenow://help/query-syntax` (it is a skill reference file), and the server instructions no longer list the skills; the tools and the other four resources are unchanged. Any other value stops startup |

`off` controls only what this server serves: the `skill://` resources, `servicenow://help/query-syntax` and the skill part of the instructions. Skills a client loads from disk are not affected. The [Claude Code plugin](clients.md#claude-code-plugin) installs the four skills as filesystem skills, so plugin users still get them with `off`.

- **Tools only:** add the server without the plugin (`claude mcp add servicenow -e SERVICENOW_SKILLS=off -e SERVICENOW_INSTANCE_URL=… -- uvx mcp-server-servicenow`, or an `mcp.json` entry with the variable in `env`), then load your own skills, if any, the way your client loads skills.
- **With the plugin:** `off` stops the server serving a second copy of the skills the plugin already loads.
- **Measuring what the skills add:** compare `on` and `off` with the server added without the plugin. Through the plugin, `off` leaves the skills loaded.

### One-shot commands

These run, print a report and exit; they don't start the server. Only `--check` loads a `.env` file, as the server does; the others read no instance or credential.

| CLI Arg | What it does |
|---------|--------------|
| `--check` | Read-only connection doctor: reach, identity, roles, table, schema and aggregate access |
| `--validate-skills PATH [PATH ...]` | Check skill folders against the [skill profile](skill-profile.md), offline; exit 1 on errors |
| `--strict` | With `--validate-skills`: warnings fail too |
| `--eval-mocks PLUGIN_DIR` | Write `claude plugin eval` mocks of this server's tools into the plugin's `evals/mocks/<server>/` ([eval kit](skill-profile.md#the-eval-kit)); keeps your edits |
| `--eval-summary RESULT_JSON` | Print a Markdown summary of a finished eval run for a `RESULTS.md`; exit 1 on a partial run |
| `--eval-baseline PLUGIN_DIR OUT_DIR` | Copy a skills plugin without its skills, to run the same cases against the bare tools |
| `--baseline RESULT_JSON` | With `--eval-summary`: the tools-only run, to report what the skills add |
| `--badge FILE` | With `--eval-summary`: also write a shields.io endpoint badge |

Boolean env vars accept `1`, `true`, `yes`, `on` (case-insensitive). Empty values and unexpanded `${VAR}` placeholders (as Claude Code passes for unset plugin env vars) are treated as unset.
