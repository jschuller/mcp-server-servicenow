# Client setup

Every snippet below assumes the [start-here](../README.md#2-create-an-integration-user) identity: user `mcp.integration` (*Web service access only*, roles `itil` + `snc_read_only`) and `--read-only`. Drop `--read-only` once the user has write roles. You need [uv](https://docs.astral.sh/uv/getting-started/installation/) (`uvx` runs the server without installing it): `curl -LsSf https://astral.sh/uv/install.sh | sh` on macOS/Linux, `winget install astral-sh.uv` on Windows.

Basic auth is the default (`SERVICENOW_AUTH_TYPE=basic`). OAuth, API keys, multiple instances and a launcher that reads secrets from your OS store: [configuration.md](configuration.md).

## Claude Code

macOS / Linux:

```bash
read -rs SERVICENOW_PASSWORD     # paste the password; it is not shown or kept in your history
claude mcp add servicenow \
  -e SERVICENOW_INSTANCE_URL=https://devNNNNNN.service-now.com \
  -e SERVICENOW_USERNAME=mcp.integration \
  -e SERVICENOW_PASSWORD="$SERVICENOW_PASSWORD" \
  -- uvx mcp-server-servicenow --read-only
```

Windows (PowerShell 5.1 or 7):

```powershell
$s = Read-Host 'Password' -AsSecureString
$p = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
claude mcp add servicenow -e SERVICENOW_INSTANCE_URL=https://devNNNNNN.service-now.com -e SERVICENOW_USERNAME=mcp.integration -e "SERVICENOW_PASSWORD=$p" -- uvx mcp-server-servicenow --read-only
```

Claude Code keeps the value in its own config (`~/.claude.json`); for a company instance, use a launcher from [keeping secrets out of config files](configuration.md#keeping-secrets-out-of-config-files).

### Claude Code plugin

The plugin wires up the same server and also installs the four skills as filesystem skills, so they appear as `/servicenow:triaging-incidents`, `/servicenow:servicenow-cmdb`, `/servicenow:reviewing-update-sets` and `/servicenow:exploring-tables`.

```bash
export SERVICENOW_INSTANCE_URL="https://devNNNNNN.service-now.com"
export SERVICENOW_USERNAME="mcp.integration"
read -rs SERVICENOW_PASSWORD && export SERVICENOW_PASSWORD
# OAuth instead: SERVICENOW_AUTH_TYPE=oauth, SERVICENOW_CLIENT_ID, SERVICENOW_CLIENT_SECRET

claude plugin marketplace add jschuller/mcp-server-servicenow
claude plugin install servicenow@mcp-server-servicenow
```

The plugin reads these variables from the shell that starts Claude Code. To develop on it: `claude --plugin-dir /path/to/mcp-server-servicenow`. 0.8.0 renamed the 0.7.x commands (see the [changelog](../CHANGELOG.md)).

## Claude Desktop

Edit `claude_desktop_config.json` — macOS: `~/Library/Application Support/Claude/`, Windows: `%APPDATA%\Claude\`:

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": ["mcp-server-servicenow", "--read-only"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://devNNNNNN.service-now.com",
        "SERVICENOW_USERNAME": "mcp.integration",
        "SERVICENOW_PASSWORD": "your-password"
      }
    }
  }
}
```

Claude Desktop does not expand `${VAR}`, so the password sits in this file; a [launcher](configuration.md#keeping-secrets-out-of-config-files) keeps it out. If Desktop reports `spawn uvx ENOENT`, use the full path from `which uvx` (macOS) or `where uvx` (Windows) as `command`.

## VS Code (GitHub Copilot)

Add to `.vscode/mcp.json` in your workspace, or run **MCP: Open User Configuration**. VS Code asks for the URL and password on first start and stores them securely:

```json
{
  "inputs": [
    { "type": "promptString", "id": "servicenow-url", "description": "ServiceNow instance URL, e.g. https://devNNNNNN.service-now.com" },
    { "type": "promptString", "id": "servicenow-password", "description": "Password for mcp.integration", "password": true }
  ],
  "servers": {
    "servicenow": {
      "type": "stdio",
      "command": "uvx",
      "args": ["mcp-server-servicenow", "--read-only"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "${input:servicenow-url}",
        "SERVICENOW_USERNAME": "mcp.integration",
        "SERVICENOW_PASSWORD": "${input:servicenow-password}"
      }
    }
  }
}
```

Use Copilot Chat in **Agent** mode; the tools appear under the tools picker.

## Cursor

Add to `.cursor/mcp.json` (project) or `~/.cursor/mcp.json`; Cursor reads the password from the environment it was started in:

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": ["mcp-server-servicenow", "--read-only"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://devNNNNNN.service-now.com",
        "SERVICENOW_USERNAME": "mcp.integration",
        "SERVICENOW_PASSWORD": "${env:SERVICENOW_PASSWORD}"
      }
    }
  }
}
```

Not yet verified against this release.

## Codex CLI

```bash
codex mcp add servicenow \
  --env SERVICENOW_INSTANCE_URL=https://devNNNNNN.service-now.com \
  --env SERVICENOW_USERNAME=mcp.integration \
  -- uvx mcp-server-servicenow --read-only
```

Then forward the password from your shell instead of writing it to `~/.codex/config.toml`: add `env_vars = ["SERVICENOW_PASSWORD"]` under `[mcp_servers.servicenow]` ([example](configuration.md#codex-cli-codexconfigtoml)). Codex auto-approves tools annotated `readOnlyHint` and asks before the rest.

## Antigravity CLI (Gemini)

```bash
read -rs SERVICENOW_PASSWORD
agy mcp add \
  -e SERVICENOW_INSTANCE_URL=https://devNNNNNN.service-now.com \
  -e SERVICENOW_USERNAME=mcp.integration \
  -e SERVICENOW_PASSWORD="$SERVICENOW_PASSWORD" \
  servicenow uvx mcp-server-servicenow --read-only
```

Antigravity asks before every MCP tool call, read-only ones included, and print mode (`agy -p`) denies what it cannot ask about. For a read-only server you can pre-approve its tools in `~/.gemini/antigravity-cli/settings.json`: `"permissions": {"allow": ["mcp(servicenow/*)"]}`.

## Gemini CLI

Add to `~/.gemini/settings.json` (or `.gemini/settings.json` in a trusted project); Gemini CLI expands `$VAR` from its environment:

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": ["mcp-server-servicenow", "--read-only"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "https://devNNNNNN.service-now.com",
        "SERVICENOW_USERNAME": "mcp.integration",
        "SERVICENOW_PASSWORD": "$SERVICENOW_PASSWORD"
      }
    }
  }
}
```

Not verified: on 2026-10-11 Gemini CLI 0.63.0 no longer accepted personal Google sign-in ("migrate to Antigravity"), so it needs a Gemini API key or a Google Cloud project.

## pi

```bash
pi mcp add servicenow --exposure direct \
  --env SERVICENOW_INSTANCE_URL=https://devNNNNNN.service-now.com \
  --env SERVICENOW_USERNAME=mcp.integration \
  --env 'SERVICENOW_PASSWORD=${SERVICENOW_PASSWORD}' \
  -- uvx mcp-server-servicenow --read-only
pi mcp list   # connects and lists 12 tools, 15 resources
```

`--exposure direct` lets the model call the tools by name (pi's default, `codemode`, wraps them in scripts). pi has no permission prompts: keep `--read-only` unless you want the model to write unasked.

## How clients use the skills

- **Claude Code** reads them on its own: the server's `instructions` tell the model which skill matches which request, and the model fetches the resource before calling tools. The plugin also installs the same four files as filesystem skills.
- **Codex CLI and pi** expose MCP resources to the model (`list_mcp_resources` / `read_mcp_resource`). Codex follows the instructions and reads the matching skill unprompted; pi passes only their first line, so its model reads a skill when asked. Both also load the same `SKILL.md` folders from disk (`~/.agents/skills/`, or pi's `--skill <dir>`).
- **Antigravity CLI** loads tools on demand and reads the server's `instructions`; it read the CMDB skill and a reference file unprompted before querying.
- **Claude Desktop** lists them under the server's connector entry in the `+` menu; attaching one reads it over MCP (verified on Desktop 1.46388.4).
- **Hosts implementing SEP-2640** list them next to local skills. The server will declare the extension (`skills/list`) once FastMCP ships it.
- **Any other client that surfaces MCP resources** — VS Code's *Add Context → MCP Resources*, for example — can attach them like any resource.

## Verified clients

Checked on 2026-10-10/11 against ServiceNow Brazil instances (stdio, read-only identity, this release):

| | Claude Code 2.1.296 | Codex CLI 0.162.1 | Antigravity CLI 1.1.20 | pi 1.1.0 |
|---|---|---|---|---|
| Protocol negotiated | 2026-07-28 | 2025-06-18 | not recorded | 2025-11-25 |
| Tools + annotations | ✓ (12 in `--read-only`) | ✓ read-only tools run without approval; `codex exec` refuses the rest | ✓ loaded on demand; asks before every MCP call | ✓ (`--exposure direct`) |
| Skills as MCP resources | ✓ read before querying, unprompted | ✓ read before querying, unprompted | ✓ read before querying, unprompted | ✓ when asked (pi passes only the first line of `instructions`) |
| Skills from disk | ✓ plugin: `/servicenow:<skill>` | not tested | not tested | listed with `--skill <dir>` |
| Write tools | permission prompt before each (default mode) | approval prompt in the TUI; `codex exec` refuses them | permission prompt; print mode denies | no prompt: use `--read-only` |

The write paths (create/update/delete, update sets, schema) were checked separately over Streamable HTTP with an admin's own ServiceNow OAuth token forwarded per user: `scripts/stdio_smoke.py --profile write`, 33/33, audit lines carry the caller (`"user":"admin","auth_mode":"oauth"`).
