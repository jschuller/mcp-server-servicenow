# Client setup

Every snippet below assumes the [start-here](../README.md#2-create-an-integration-user) identity: user `mcp.integration` (*Web service access only*, roles `itil` + `snc_read_only`). Because it holds `snc_read_only`, the server lists only the 13 read-only tools; with a user that can write, all 20 appear and your client decides when to ask. Add `--read-only` for a writable identity on a client without approval prompts (opencode, pi) or on a shared HTTP server. You need [uv](https://docs.astral.sh/uv/getting-started/installation/) (`uvx` runs the server without installing it): `curl -LsSf https://astral.sh/uv/install.sh | sh` on macOS/Linux, `winget install astral-sh.uv` on Windows.

Basic auth is the default (`SERVICENOW_AUTH_TYPE=basic`). OAuth, API keys, multiple instances and a launcher that reads secrets from your OS store: [configuration.md](configuration.md).

## Claude Code

macOS / Linux:

```bash
read -rs SERVICENOW_PASSWORD     # paste the password; it is not shown or kept in your history
claude mcp add servicenow \
  -e SERVICENOW_INSTANCE_URL=https://devNNNNNN.service-now.com \
  -e SERVICENOW_USERNAME=mcp.integration \
  -e SERVICENOW_PASSWORD="$SERVICENOW_PASSWORD" \
  -- uvx mcp-server-servicenow
```

Windows (PowerShell 5.1 or 7):

```powershell
$s = Read-Host 'Password' -AsSecureString
$p = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
claude mcp add servicenow -e SERVICENOW_INSTANCE_URL=https://devNNNNNN.service-now.com -e SERVICENOW_USERNAME=mcp.integration -e "SERVICENOW_PASSWORD=$p" -- uvx mcp-server-servicenow
```

Claude Code keeps the value in its own config (`~/.claude.json`); for a company instance, use a launcher from [keeping secrets out of config files](configuration.md#keeping-secrets-out-of-config-files).

### Claude Code plugin

The plugin wires up the same server and also installs the four skills as filesystem skills, so they appear as `/servicenow:servicenow-cmdb`, `/servicenow:reviewing-update-sets`, `/servicenow:exploring-tables` and `/servicenow:analyzing-access`.

```bash
export SERVICENOW_INSTANCE_URL="https://devNNNNNN.service-now.com"
export SERVICENOW_USERNAME="mcp.integration"
read -rs SERVICENOW_PASSWORD && export SERVICENOW_PASSWORD
# OAuth instead: SERVICENOW_AUTH_TYPE=oauth, SERVICENOW_CLIENT_ID, SERVICENOW_CLIENT_SECRET

claude plugin marketplace add jschuller/mcp-server-servicenow
claude plugin install servicenow@mcp-server-servicenow
```

The plugin reads these variables from the shell that starts Claude Code. It runs the server release it ships with (`uvx mcp-server-servicenow==X.Y.Z`), so updating the plugin brings the next server too. To develop on it: `claude --plugin-dir /path/to/mcp-server-servicenow`. 0.8.0 renamed the 0.7.x commands (see the [changelog](../CHANGELOG.md)).

## Claude Desktop

Edit `claude_desktop_config.json` — macOS: `~/Library/Application Support/Claude/`, Windows: `%APPDATA%\Claude\`:

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": ["mcp-server-servicenow"],
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
      "args": ["mcp-server-servicenow"],
      "env": {
        "SERVICENOW_INSTANCE_URL": "${input:servicenow-url}",
        "SERVICENOW_USERNAME": "mcp.integration",
        "SERVICENOW_PASSWORD": "${input:servicenow-password}"
      }
    }
  }
}
```

Click **Start** above the server in `mcp.json` (or run **MCP: List Servers**), then use Copilot Chat in **Agent** mode; the 13 read-only tools appear in the tools picker. Tools annotated `readOnlyHint` run without a prompt; write tools get a **Run …** confirmation, which you can allow for the session, the workspace or always. Copilot does not read the skills on its own: attach one with **Add Context › MCP Resources** (for example `skill://servicenow-cmdb/SKILL.md`) when you want the guided workflow.

## Cursor

Add to `.cursor/mcp.json` (project) or `~/.cursor/mcp.json`; Cursor reads the password from the environment it was started in:

```json
{
  "mcpServers": {
    "servicenow": {
      "command": "uvx",
      "args": ["mcp-server-servicenow"],
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
  -- uvx mcp-server-servicenow
```

Then forward the password from your shell instead of writing it to `~/.codex/config.toml`: add `env_vars = ["SERVICENOW_PASSWORD"]` under `[mcp_servers.servicenow]` ([example](configuration.md#codex-cli-codexconfigtoml)). Codex auto-approves tools annotated `readOnlyHint` and asks before the rest.

## Antigravity CLI (Gemini)

```bash
read -rs SERVICENOW_PASSWORD
agy mcp add \
  -e SERVICENOW_INSTANCE_URL=https://devNNNNNN.service-now.com \
  -e SERVICENOW_USERNAME=mcp.integration \
  -e SERVICENOW_PASSWORD="$SERVICENOW_PASSWORD" \
  servicenow uvx mcp-server-servicenow
```

Antigravity asks before every MCP tool call, read-only ones included, and print mode (`agy -p`) denies what it cannot ask about. For a read-only server you can pre-approve its tools in `~/.gemini/antigravity-cli/settings.json`: `"permissions": {"allow": ["mcp(servicenow/*)"]}`.

**Gemini CLI:** Google now points individual users to Antigravity; on 2026-10-11 Gemini CLI 0.63.0 refused personal Google sign-in. With a Gemini API key or a Google Cloud project it takes the same `mcpServers` block as Claude Desktop in `~/.gemini/settings.json` (not verified).

## opencode

Add to `opencode.json` in your project, or `~/.config/opencode/opencode.json`; opencode fills `{env:…}` from the environment it was started in:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servicenow": {
      "type": "local",
      "command": ["uvx", "mcp-server-servicenow"],
      "environment": {
        "SERVICENOW_INSTANCE_URL": "https://devNNNNNN.service-now.com",
        "SERVICENOW_USERNAME": "mcp.integration",
        "SERVICENOW_PASSWORD": "{env:SERVICENOW_PASSWORD}"
      }
    }
  }
}
```

Check it with `opencode mcp list`. opencode **allows MCP tools without asking** by default. The start-here user already hides the write tools; with a writable identity add `--read-only`, or make it ask before every ServiceNow call with `"permission": { "servicenow_*": "ask" }` at the top level of the same file (`opencode run` then refuses those calls instead of asking).

## pi

```bash
pi mcp add servicenow --exposure direct \
  --env SERVICENOW_INSTANCE_URL=https://devNNNNNN.service-now.com \
  --env SERVICENOW_USERNAME=mcp.integration \
  --env 'SERVICENOW_PASSWORD=${SERVICENOW_PASSWORD}' \
  -- uvx mcp-server-servicenow
pi mcp list   # connects and lists 13 tools, 19 resources
```

`--exposure direct` lets the model call the tools by name (pi's default, `codemode`, wraps them in scripts). pi has no permission prompts: the start-here user already hides the write tools; with a writable identity add `--read-only` unless you want the model to write unasked.

## How clients use the skills

- **Claude Code** reads them on its own: the server's `instructions` tell the model which skill matches which request, and the model fetches the resource before calling tools. The plugin also installs the same four files as filesystem skills.
- **Codex CLI and pi** expose MCP resources to the model (`list_mcp_resources` / `read_mcp_resource`). Codex follows the instructions and reads the matching skill unprompted; pi passes only their first line, so its model reads a skill when asked. Both also load the same `SKILL.md` folders from disk (`~/.agents/skills/`, or pi's `--skill <dir>`).
- **Antigravity CLI** loads tools on demand and reads the server's `instructions`; it read the CMDB skill and a reference file unprompted before querying.
- **opencode** gives the model `list_mcp_resources` / `read_mcp_resource`; it read the CMDB skill, a reference file and the query-syntax help unprompted before querying.
- **VS Code (Copilot)** lists them under **Add Context › MCP Resources**; in our check Copilot called the tools without reading a skill first, so attach one yourself.
- **Claude Desktop** lists them under the server's connector entry in the `+` menu; attaching one reads it over MCP (verified on Desktop 1.46388.4).
- **Hosts implementing SEP-2640** list them next to local skills. The server will declare the extension (`skills/list`) once FastMCP ships it.
- **Any other client that surfaces MCP resources** — VS Code's *Add Context → MCP Resources*, for example — can attach them like any resource.

## Verified clients

Checked on 2026-10-11 with 0.8.0 against a ServiceNow Brazil PDI (stdio, read-only identity), asking for the five most recent incidents and a CMDB health summary. For 0.9.0, fresh Claude Code 2.1.296 sessions read the matching platform skill before the first data call in 28 of 28 runs, and Codex CLI 0.162.1 lists the 18 resources:

| Client | Protocol | Tools and approval | Skills over MCP |
|---|---|---|---|
| Claude Code 2.1.296 | 2026-07-28 | 12 tools (`snc_read_only` identity); permission prompt before writes (default mode); plugin adds `/servicenow:<skill>` | read before querying, unprompted |
| VS Code 1.140 + GitHub Copilot | not recorded | 12 tools in Agent mode; read-only tools run without approval; confirmation before write tools | not read on its own; attach via Add Context › MCP Resources |
| Codex CLI 0.162.1 | 2025-06-18 | read-only tools run without approval; approval prompt for the rest; `codex exec` refuses them | read before querying, unprompted |
| Antigravity CLI 1.1.20 | not recorded | loaded on demand; asks before every MCP call; print mode denies unless allowed | read before querying, unprompted |
| opencode 1.19.0 | not recorded | runs every MCP tool without asking unless `permission` says `ask` | read before querying, unprompted |
| pi 1.1.0 | 2025-11-25 | `--exposure direct`; no approval prompts | when asked (pi passes only the first line of `instructions`) |

Clients without approval prompts (opencode by default, pi) should run with `--read-only` or a read-only identity. The write paths (create/update/delete, update sets, schema) were checked separately over Streamable HTTP with an admin's own ServiceNow OAuth token forwarded per user: `scripts/stdio_smoke.py --profile write`, 33/33, audit lines carry the caller (`"user":"admin","auth_mode":"oauth"`).
