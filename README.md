<!-- mcp-server: servicenow | tools: 19 | resources: 5 | skills: 4 | transport: stdio,streamable-http | auth: basic,oauth,api_key | framework: fastmcp-4.1 -->
<!-- mcp-name: io.github.jschuller/mcp-server-servicenow -->

<p align="center">
  <img src="https://raw.githubusercontent.com/jschuller/mcp-server-servicenow/main/docs/hero.png" alt="ServiceNow MCP Server" width="100%">
</p>

<h1 align="center">ServiceNow MCP Server</h1>

<p align="center">
  <a href="https://pypi.org/project/mcp-server-servicenow/"><img src="https://img.shields.io/pypi/v/mcp-server-servicenow?color=005E4D&label=PyPI" alt="PyPI"></a>
  <a href="https://pypi.org/project/mcp-server-servicenow/"><img src="https://img.shields.io/pypi/dm/mcp-server-servicenow?color=005E4D&label=downloads" alt="Downloads"></a>
  <a href="https://github.com/jschuller/mcp-server-servicenow/actions/workflows/ci.yml"><img src="https://github.com/jschuller/mcp-server-servicenow/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/jschuller/mcp-server-servicenow/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue" alt="License"></a>
</p>

<p align="center">
  Connect Claude Code, GitHub Copilot, Codex, opencode, Antigravity or any MCP client to ServiceNow:<br>
  query any table, read schema and CMDB, review update sets. Free, MIT, works on a free developer instance.
</p>

---

`uvx mcp-server-servicenow` gives an AI assistant the ServiceNow developer data plane: the Table API, the data dictionary, Stats API aggregates, the CMDB and update sets, on any release from Tokyo up. It runs alongside ServiceNow's own MCP servers ([how they differ](https://github.com/jschuller/mcp-server-servicenow/blob/main/docs/native-mcp.md)).

## What you can ask

- *"Which fields does `cmdb_ci_server` have, including inherited ones?"*
- *"Who holds admin, and which roles are granted directly instead of through a group?"*
- *"Review update set 'Q3 fixes' before I promote it."*
- *"Which server CIs are missing an IP address or an owner?"*
- *"How many open incidents does each assignment group have?"* (any table works, not just the platform ones)

## Quick start

About ten minutes on a free developer instance. On a company instance, ask your ServiceNow admin for the user in step 2.

### 1. Get a ServiceNow instance

Sign up for a free [Personal Developer Instance (PDI)](https://developer.servicenow.com/) — it comes with demo incidents, changes and CIs. PDIs hibernate after a few hours idle: wake yours from the developer portal before you start.

### 2. Create an integration user

Don't connect as `admin`: new instances refuse REST basic auth for it ([why](https://github.com/jschuller/mcp-server-servicenow/blob/main/TROUBLESHOOTING.md#401-unauthorized)), and the server needs far less.

1. Sign in as admin and go to **All › User Administration › Users › New**.
2. **User ID** `mcp.integration`, **Identity type** *Machine* (this ticks **Web service access only**), and tick **Internal Integration User**. If your form has no Identity type, tick Web service access only yourself. **Submit**, then open the user again.
3. **Set Password**, and keep the password for step 3.
4. **Roles › Edit**: add `itil` and `snc_read_only`, save.

That user can read incidents, changes, problems, CMDB and aggregates, and can't change anything. Schema, update sets and writes need more: see [roles](#roles).

### 3. Add the server to your client

You need [uv](https://docs.astral.sh/uv/getting-started/installation/) (`uvx` runs the server without installing it). In Claude Code:

```bash
read -rs SERVICENOW_PASSWORD     # paste the password; it is not shown or kept in your history
claude mcp add servicenow \
  -e SERVICENOW_INSTANCE_URL=https://devNNNNNN.service-now.com \
  -e SERVICENOW_USERNAME=mcp.integration \
  -e SERVICENOW_PASSWORD="$SERVICENOW_PASSWORD" \
  -- uvx mcp-server-servicenow
```

Or install the Claude Code plugin, which adds the four skills as slash commands. It reads the same `SERVICENOW_*` variables from the shell that starts Claude Code ([details](https://github.com/jschuller/mcp-server-servicenow/blob/main/docs/clients.md#claude-code-plugin)):

```
/plugin install servicenow --marketplace jschuller/mcp-server-servicenow
```

<details>
<summary><strong>Windows (PowerShell)</strong></summary>

Install uv with `winget install astral-sh.uv`, then:

```powershell
$s = Read-Host 'Password' -AsSecureString
$p = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
claude mcp add servicenow -e SERVICENOW_INSTANCE_URL=https://devNNNNNN.service-now.com -e SERVICENOW_USERNAME=mcp.integration -e "SERVICENOW_PASSWORD=$p" -- uvx mcp-server-servicenow
```
</details>

<details>
<summary><strong>VS Code (GitHub Copilot)</strong></summary>

[![Install in VS Code](https://img.shields.io/badge/VS_Code-Install_server-0098FF?logo=visualstudiocode&logoColor=white)](https://vscode.dev/redirect/mcp/install?name=servicenow&inputs=%5B%7B%22type%22%3A%22promptString%22%2C%22id%22%3A%22servicenow-url%22%2C%22description%22%3A%22ServiceNow%20instance%20URL%2C%20e.g.%20https%3A%2F%2FdevNNNNNN.service-now.com%22%7D%2C%7B%22type%22%3A%22promptString%22%2C%22id%22%3A%22servicenow-username%22%2C%22description%22%3A%22ServiceNow%20integration%20user%22%2C%22default%22%3A%22mcp.integration%22%7D%2C%7B%22type%22%3A%22promptString%22%2C%22id%22%3A%22servicenow-password%22%2C%22description%22%3A%22Password%20for%20the%20integration%20user%22%2C%22password%22%3Atrue%7D%5D&config=%7B%22type%22%3A%22stdio%22%2C%22command%22%3A%22uvx%22%2C%22args%22%3A%5B%22mcp-server-servicenow%22%5D%2C%22env%22%3A%7B%22SERVICENOW_INSTANCE_URL%22%3A%22%24%7Binput%3Aservicenow-url%7D%22%2C%22SERVICENOW_USERNAME%22%3A%22%24%7Binput%3Aservicenow-username%7D%22%2C%22SERVICENOW_PASSWORD%22%3A%22%24%7Binput%3Aservicenow-password%7D%22%7D%7D)

The button adds the server to your VS Code user profile and asks for the instance URL, user and password on first start, storing the password securely. Or add this to `.vscode/mcp.json`. Use Copilot Chat in **Agent** mode.

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
</details>

<details>
<summary><strong>Claude Desktop</strong></summary>

Edit `claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/`, Windows: `%APPDATA%\Claude\`):

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
</details>

Codex, opencode, Antigravity, Cursor, pi, the Claude Code plugin and keeping the password out of config files: [client setup](https://github.com/jschuller/mcp-server-servicenow/blob/main/docs/clients.md).

### 4. Check it works

Ask: *"List the 5 most recent incidents."* The start-here user holds `snc_read_only`, so the server lists only the 12 read-only tools. Give the user write roles (and remove `snc_read_only`) and the 7 write tools appear; your client asks before each write.

No answer? Run the same configuration with `--check`. It makes read-only requests, prints one line per check (instance reachable, identity, roles, table read, schema, aggregates) and never prints a secret:

```bash
SERVICENOW_INSTANCE_URL=https://devNNNNNN.service-now.com SERVICENOW_USERNAME=mcp.integration \
  SERVICENOW_PASSWORD="$SERVICENOW_PASSWORD" uvx mcp-server-servicenow --check
```

Got an answer back? Say which client and ServiceNow release in [Show and tell](https://github.com/jschuller/mcp-server-servicenow/discussions/categories/show-and-tell) — it tells us what works. Questions go to [Q&A](https://github.com/jschuller/mcp-server-servicenow/discussions/categories/q-a).

## If it doesn't work

| You see | Fix |
|---|---|
| `Got HTML instead of JSON` | The PDI is asleep: [wake it](https://developer.servicenow.com/dev.do#!/home?wu=true) and retry |
| `401` | The user isn't *Web service access only*, or the password is wrong ([401](https://github.com/jschuller/mcp-server-servicenow/blob/main/TROUBLESHOOTING.md#401-unauthorized)) |
| `403` | The user lacks a role for that table or tool ([roles](#roles)) |

Everything else: run `--check` ([above](#4-check-it-works)), then [TROUBLESHOOTING](https://github.com/jschuller/mcp-server-servicenow/blob/main/TROUBLESHOOTING.md).

## Tools

19 tools, 5 resources and 4 skills. Full reference: [tools, resources and skills](https://github.com/jschuller/mcp-server-servicenow/blob/main/docs/tools.md).

| Group | Tools |
|---|---|
| Table API | `list_records` `get_record` `create_record` `update_record` `delete_record` `aggregate_records` |
| CMDB | `list_ci` `get_ci` `create_ci` `update_ci` `get_ci_relationships` |
| System | `get_table_schema` `get_current_user` `get_system_properties` |
| Update sets | `list_update_sets` `get_update_set` `create_update_set` `set_current_update_set` `list_update_set_changes` |

**Resources:** table schemas, instance info, the current update set, the CMDB class hierarchy and an encoded-query reference — read without a tool call.

**Skills:** four guided workflows for the Now Platform, served over MCP as `skill://` resources so every client gets them with no plugin:
- `exploring-tables`: schemas, choice lists, the encoded-query reference;
- `analyzing-access`: who holds which roles, and what a 403 or a missing field means;
- `reviewing-update-sets`: risk categories and a pre-promotion checklist;
- `servicenow-cmdb`: CMDB data quality and CSDM conformance.

**Community skills:** skills for applications such as ITSM, and for your own conventions, live in their authors' repositories, each with its own eval results:
- [EXTENDING.md](https://github.com/jschuller/mcp-server-servicenow/blob/main/EXTENDING.md) covers writing, validating, testing with mocked tools, and sharing them;
- to find them, browse the [`servicenow-mcp-skill`](https://github.com/topics/servicenow-mcp-skill) topic and [Discussions › Skills](https://github.com/jschuller/mcp-server-servicenow/discussions/categories/skills). This project doesn't vet them.

The incident triage skill that shipped here until 0.9.0 is now an [example](https://github.com/jschuller/mcp-server-servicenow/tree/main/examples/incident-triage).

## Roles

ServiceNow's ACLs decide what the user can do; the server adds nothing on top.

| You want | Roles | Run with |
|---|---|---|
| Read ITSM and CMDB data (the [start-here](#2-create-an-integration-user) user) | `itil` + `snc_read_only` | no flag: write tools are hidden for `snc_read_only` |
| …and create or update incidents and CIs | `itil` (no `snc_read_only`) | no flag; the client asks before writes (`--read-only` on clients that don't ask) |
| …and delete incidents, problems, changes | add `itil_admin` | |
| Table schemas | add `personalize_dictionary` | |
| Update sets, system properties | `admin` — on a PDI only | |

Per-tool detail: [roles per tool](https://github.com/jschuller/mcp-server-servicenow/blob/main/docs/tools.md#roles). Setting up a company instance: [recommended integration identity](https://github.com/jschuller/mcp-server-servicenow/blob/main/docs/configuration.md#recommended-integration-identity).

## Safety and governance

- **Read-only mode** — `--read-only` hides the 7 write tools and refuses any non-GET request.
- **Read-only identities see read-only tools** — when the user holds `snc_read_only` the write tools are hidden without a flag. A convenience, not a control: ServiceNow refuses those writes anyway.
- **Table scope lives in ServiceNow** — ACLs and REST API access policies on the integration user decide which tables and fields it can read, dot-walks included.
- **Audit log** — one JSON line per tool call or resource read: who, which table, outcome; written fields by name only, never their values, and secret-like values in queries masked.
- **Your client approves writes** — every tool is annotated read-only or destructive, so Claude Code, Copilot and Codex ask before a write. Clients that don't ask (opencode by default, pi) need a read-only identity, or `--read-only` when the identity can write.

Flags and environment variables: [configuration](https://github.com/jschuller/mcp-server-servicenow/blob/main/docs/configuration.md#safety-rails).

## Works with

Verified with 0.8.0 on 2026-10-11 against ServiceNow Brazil, and the 0.9.0 skills re-checked in Claude Code and Codex: Claude Code 2.1.296, VS Code 1.140 with GitHub Copilot, Codex CLI 0.162.1, opencode 1.19.0, Antigravity CLI 1.1.20 and pi 1.1.0. Claude Desktop, Cursor and any other client that speaks MCP over stdio or Streamable HTTP should work too; behaviour per client: [client setup](https://github.com/jschuller/mcp-server-servicenow/blob/main/docs/clients.md#verified-clients).

## More

- [Client setup](https://github.com/jschuller/mcp-server-servicenow/blob/main/docs/clients.md) — every client, the Claude Code plugin, Windows
- [Configuration](https://github.com/jschuller/mcp-server-servicenow/blob/main/docs/configuration.md) — the recommended identity, OAuth client credentials (headless), API keys, multiple instances, secrets, every setting
- [Remote deployment](https://github.com/jschuller/mcp-server-servicenow/blob/main/docs/deployment.md) — from source, Streamable HTTP, OAuth 2.1 + PKCE, Docker, Cloud Run
- [Alongside ServiceNow's own MCP servers](https://github.com/jschuller/mcp-server-servicenow/blob/main/docs/native-mcp.md)
- [Architecture and embedding](https://github.com/jschuller/mcp-server-servicenow/blob/main/docs/architecture.md) — mount it in your own FastMCP server
- [Write your own skills](https://github.com/jschuller/mcp-server-servicenow/blob/main/EXTENDING.md) — the template, the validator, the GitHub Action, sharing
- [Privacy](https://github.com/jschuller/mcp-server-servicenow/blob/main/docs/privacy.md) — the server talks only to your instance; no telemetry
- [Contributing](https://github.com/jschuller/mcp-server-servicenow/blob/main/CONTRIBUTING.md) · [Changelog](https://github.com/jschuller/mcp-server-servicenow/blob/main/CHANGELOG.md) · [Support](https://github.com/jschuller/mcp-server-servicenow/blob/main/SUPPORT.md) · [Security](https://github.com/jschuller/mcp-server-servicenow/blob/main/SECURITY.md)

Write your own skills: [EXTENDING.md](https://github.com/jschuller/mcp-server-servicenow/blob/main/EXTENDING.md) covers the template, the validator and how to share them. Next: MCP prompts.

**Related:** [sn-app-template](https://github.com/jschuller/sn-app-template) — a ServiceNow scoped app template for Claude Code + now-sdk that pairs with this server.

## License

[MIT](https://github.com/jschuller/mcp-server-servicenow/blob/main/LICENSE). An independent project, not affiliated with or endorsed by ServiceNow, Inc. ServiceNow is a trademark of ServiceNow, Inc.
