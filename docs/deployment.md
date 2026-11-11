# Deployment Guide

## From source

```bash
git clone https://github.com/jschuller/mcp-server-servicenow.git
cd mcp-server-servicenow
uv sync

export SERVICENOW_INSTANCE_URL=https://devNNNNNN.service-now.com
export SERVICENOW_USERNAME=mcp.integration
read -rs SERVICENOW_PASSWORD && export SERVICENOW_PASSWORD

uv run mcp-server-servicenow --read-only          # stdio, for local clients

# Streamable HTTP (remote access / Cloud Run) fails closed: it needs MCP
# endpoint auth on top of the ServiceNow credentials. Static bearer tokens
# here; OAuth 2.1 + PKCE below. Make the token first, so your client can use
# it; the server reads it from the environment, not the command line.
export MCP_STATIC_TOKENS="local:$(openssl rand -hex 32)"
echo "${MCP_STATIC_TOKENS#local:}"                 # the bearer token for your client
uv run mcp-server-servicenow --transport streamable-http --port 8080 --read-only
```

Each static token is `token` or `name:token`; the name is what the audit log records as `user`, so it stays the same when you
reorder the list. A token shorter than 32 characters logs a warning at startup. Without `--read-only`, an HTTP
listener also warns at startup: the server doesn't confirm writes, the MCP client does, and every static token writes
as the one service account.

## Headless and CI

Use OAuth client credentials ([configuration.md](configuration.md#oauth-client-credentials-headless)): no user password and no browser sign-in, and the secret comes from your CI secret store as `SERVICENOW_CLIENT_SECRET`. Give the OAuth application user `itil` + `snc_read_only` so the write tools are hidden, and keep `--read-only` on when the identity could write.

- **Claude Code:** `claude -p "…" --mcp-config servicenow.json --allowedTools "mcp__servicenow__list_records,mcp__servicenow__get_record"`. Name every tool the job may use; anything else is refused without a prompt.
- **Codex:** `codex exec` runs tools annotated read-only without asking and refuses write tools.
- **GitHub Copilot's cloud agent** uses MCP tools only and ignores resources, so it won't read the skills; put the steps in the task instead.

## Docker / Cloud Run

```bash
# Build
docker build -t mcp-server-servicenow .

# Run locally
# The server fails closed: an HTTP listener requires MCP endpoint auth
# (MCP_STATIC_TOKENS or MCP_OAUTH_*), otherwise it exits at startup.
# `-e NAME` with no value passes the variable from your shell, so the
# password and token stay out of shell history and `ps`.
read -rs SERVICENOW_PASSWORD && export SERVICENOW_PASSWORD
export MCP_STATIC_TOKENS="docker:$(openssl rand -hex 32)"
docker run -p 8080:8080 \
  -e SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com \
  -e SERVICENOW_AUTH_TYPE=basic \
  -e SERVICENOW_USERNAME=mcp.integration \
  -e SERVICENOW_PASSWORD \
  -e MCP_STATIC_TOKENS \
  -e SERVICENOW_READ_ONLY=true \
  mcp-server-servicenow

# Deploy to Cloud Run with global creds (requires GCP IAM for access).
# Secrets come from Secret Manager (--set-secrets), not plain env vars that
# anyone with viewer access can read in the revision config.
gcloud run deploy servicenow-mcp \
  --source . \
  --region us-east1 \
  --port 8080 \
  --no-allow-unauthenticated \
  --set-env-vars "SERVICENOW_INSTANCE_URL=..." \
  --set-env-vars "SERVICENOW_AUTH_TYPE=basic" \
  --set-env-vars "SERVICENOW_USERNAME=..." \
  --set-env-vars "SERVICENOW_READ_ONLY=true" \
  --set-env-vars "MCP_TRANSPORT=streamable-http" \
  --set-secrets "SERVICENOW_PASSWORD=sn-password:latest" \
  --set-secrets "MCP_STATIC_TOKENS=mcp-static-tokens:latest"

# Deploy to Cloud Run with OAuth (per-user auth, publicly accessible)
gcloud run deploy servicenow-mcp \
  --source . \
  --region us-east1 \
  --port 8080 \
  --allow-unauthenticated \
  --set-env-vars "SERVICENOW_INSTANCE_URL=..." \
  --set-env-vars "MCP_OAUTH_CLIENT_ID=..." \
  --set-env-vars "MCP_BASE_URL=https://servicenow-mcp-xxxxx.run.app" \
  --set-env-vars "MCP_TRANSPORT=streamable-http" \
  --set-secrets "MCP_OAUTH_CLIENT_SECRET=mcp-oauth-client-secret:latest"
```

Before those deploys, create each secret once with `gcloud secrets create <name> --data-file=-` (the value on
stdin), and give the Cloud Run service account `roles/secretmanager.secretAccessor` on it.

## Verify HTTP Transport

```bash
# Local testing — an Authorization header is always required now
# (unauthenticated HTTP listeners no longer exist; the server fails closed).
# The bearer is the token part of MCP_STATIC_TOKENS (one entry), without its
# `name:`. curl reads the header from stdin (-H @-), so the token stays out of
# the process list.
printf 'Authorization: Bearer %s\n' "${MCP_STATIC_TOKENS#*:}" | curl -X POST http://localhost:8080/mcp \
  -H @- \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}},"id":1}'

# Cloud Run (GCP IAM in front, MCP static token for the server). IAM reads
# the Google identity token from X-Serverless-Authorization, which leaves
# Authorization for the MCP token.
curl -X POST https://your-service-url.run.app/mcp \
  -H "X-Serverless-Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Authorization: Bearer <the token part of one MCP_STATIC_TOKENS entry>" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}},"id":1}'
```

## Security Model

Three deployment modes with increasing security:

| Mode | MCP Endpoint Auth | SN Backend Auth | Use Case |
|------|------------------|-----------------|----------|
| **stdio** | None (local process) | Global creds (env vars) | Claude Desktop, Claude Code |
| **HTTP + static tokens** | Bearer tokens (`MCP_STATIC_TOKENS`) | Service account (env vars, **required** — basic, api_key or OAuth client creds); every caller shares one ServiceNow identity, so pair with `--read-only` or an `snc_read_only` identity | CI/CD, development |
| **HTTP + OAuth** | OAuth 2.1 + PKCE | Per-user SN token | Production, Cloud Run |

An unauthenticated HTTP listener is not supported: the server **fails closed**
and refuses to start a non-stdio transport unless `MCP_OAUTH_*` or
`MCP_STATIC_TOKENS` is configured. HTTP transport also binds `127.0.0.1` by
default — set `MCP_HOST=0.0.0.0` to listen on all interfaces (the Docker image
does this, since the container boundary provides the isolation).

### OAuth 2.1 + PKCE (recommended for production)

When deployed with OAuth, each user authenticates with their own ServiceNow credentials. The server acts as an OAuth proxy: it handles DCR and consent locally, redirects users to ServiceNow for login, then exchanges the auth code for SN tokens server-side.

**Defense in depth:** OAuth 2.1 + PKCE on the MCP endpoint, per-user SN ACLs on every API call, encrypted token storage, CSRF-protected consent screen.

**Setup:**

1. In ServiceNow, go to **System OAuth > Application Registry** and create an OAuth API endpoint for external clients
2. Set the redirect URI to `{your-server-url}/auth/callback`
3. On Zurich+ instances, set **Scope Restriction = "Broadly scoped"** on the OAuth app (the "Securely scoped" default limits tokens to REST API Access Policy-listed endpoints, so Table API calls fail with `invalid_token`) — or define REST API Access Policies covering the Table/Stats APIs
4. Deploy with OAuth env vars:

```bash
SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com
MCP_OAUTH_CLIENT_ID=<from Application Registry>
MCP_OAUTH_CLIENT_SECRET=<from Application Registry>
MCP_BASE_URL=https://your-mcp-server.run.app
MCP_TRANSPORT=streamable-http
```

5. In Claude.ai, add the server URL as an MCP connector — the OAuth flow handles the rest

**Requires:** ServiceNow San Diego+ (2022) for PKCE support.

### Guardrails in HTTP deployments

All safety flags work over HTTP. The audit log records the OAuth user (`claims.user_name`), the static token's name, or `oauth-client:<client_id>` for a client-credentials service account; send it to a file or let the platform collect stderr (Cloud Run → Cloud Logging).

## Behind ServiceNow AI Gateway

**Untested.** We had no instance with AI Gateway, so nothing in this section has been run against one. What it says about ServiceNow comes from ServiceNow's Brazil documentation, read on 2026-11-09 ([sources](#sources-for-this-section)). What it says about this server comes from its code and from a local probe of its OAuth endpoints. Read it as "expected to work per the documentation", not as a statement that the two are compatible.

AI Gateway is the part of AI Control Tower that sits between AI agents and MCP servers. An AI steward adds a remote MCP server by URL and approves it. Agents then call a URL on the instance instead of the server's own URL ([Managing MCP server records][aigw-record]):

```
https://<instance-url>/sncapps/aigw/mcp/<mcp-server>
```

The same page calls `/sncapps/awh/<mcp-server>/mcp` the previous format. One other page still uses it as its example ([Connecting agents through AI Gateway][aigw-connect]).

### Onboarding

1. Run this server over Streamable HTTP in the [OAuth 2.1 + PKCE](#oauth-21--pkce-recommended-for-production) mode, with `--read-only` (see [Identity](#identity-one-read-only-integration-user)).
2. In AI Control Tower, a user with the `sn_ai_governance.ai_steward` role adds the server by its `/mcp` URL (`{MCP_BASE_URL}/mcp`) and selects **Dynamic client registration** ([Add an MCP server from AI Control Tower][aigw-intake]).
3. The server is then "an unmanaged asset with a status of In review". Agents can call it through the gateway after the steward moves it to managed and completes the Onboard playbook: Assess, Build and Test, Deploy ([Exploring AI Gateway][aigw-exploring]).

What the documentation asks for, and what this server does:

- **Streamable HTTP only.** "AI Gateway does not support the SSE transport type" ([Add an MCP server from MCP Catalog][aigw-catalog]). This server's HTTP transport is Streamable HTTP.
- **OAuth only on that form.** Its client registration types are Dynamic client registration (DCR) and Manual registration. It has no field for a static bearer token, so `MCP_STATIC_TOKENS` does not fit it. A server can also reach the inventory from AI Agent Studio or the MCP Catalog; this section does not cover those routes.
- **DCR gives the gateway a public client.** ServiceNow writes that with DCR "AI Control Tower automatically receives the Client ID and Client secret". This server's registration endpoint always answers with `token_endpoint_auth_method: none` and no client secret, whatever the request asks for, and requires PKCE (S256) instead. Whether AI Control Tower accepts that answer is not known.
- **Manual registration is not a supported path.** It asks you to "create the client externally on the MCP provider side" and to enter, among other fields, a client ID, a client secret and a token revocation URL. This server has no pre-registered client to hand out (clients are created at run time) and serves no revocation endpoint.
- **The client credentials grant is not offered on this hop.** The server's authorization endpoints offer the authorization code grant, with refresh tokens, and nothing else. A person signs in to ServiceNow in a browser once to authorize the gateway's connection. (The [client credentials setup](configuration.md#oauth-client-credentials-headless) is for the other hop, from this server to ServiceNow, in the stdio and static-token modes.)

### Identity: one read-only integration user

ServiceNow describes a variant as "one of the connections registered for the same MCP server URL, for example by different users or with different credentials" ([AI Gateway Overview tab][aigw-overview-tab]). Our reading, which is an inference and not verified: every agent behind one variant reaches ServiceNow as whoever completed this server's consent page and the ServiceNow sign-in when the gateway's connection was authorized. So:

- **Authorize as a dedicated integration user that holds `snc_read_only` and is not an admin.** Not a person's account, and not `admin` ([recommended integration identity](configuration.md#recommended-integration-identity), [roles](tools.md#roles)).
- **Run the server with `--read-only` as well.** It hides the write tools and refuses any non-GET request at the HTTP layer ([safety rails](tools.md#safety-rails)), whoever authorizes later.

ServiceNow's ACLs then cap every agent at what that one user can read. Which client may call which tool is the gateway's job, not this server's. Its client access policies are off until a user with the `aig_admin` role turns on client access control for the instance ([Controlling which tools clients can access][aigw-client-access]).

### The audit log records the gateway, not the end client

ServiceNow says: "Because the MCP server receives requests from AI Gateway rather than from the clients behind it, the MCP server can't tell which client sent a request" ([Controlling which tools clients can access][aigw-client-access]). This server's [audit log](tools.md#safety-rails) still writes one line per call, but `user` is the identity that authorized the gateway's connection, the same on every line. Which agent made a call is in the gateway's own records: "AI Gateway records each call" ([Exploring AI Gateway][aigw-exploring]). No gateway page says that it forwards a client identity or a trace header to the server.

### Tool scan: failing tools are deactivated automatically

The gateway scans each tool it fetches and assigns a threat category "based on the OWASP MCP Top 10", such as `excessive_permissions`, `tool_poisoning` or `credential_harvesting` ([Managing your AI Gateway][aigw-manage]). These defaults then act on the tools ([AI Gateway roles and system properties][aigw-properties], [AI Gateway Tools tab][aigw-tools-tab]):

| Property | Default | Effect |
|---|---|---|
| `sn_awh_config.auto_update_tools_on_scan` | `true` | Tools the scan finds vulnerable are deactivated automatically, "including tools that are in use". They are activated again when a later scan finds the vulnerability removed |
| `sn_awh_config.auto_enable_new_tools` | `true` | Tools fetched after the server is approved are activated automatically |
| `sn_awh_config.pii_enabled` | `true` | The Data Sensitivity Check is on for all servers (next section) |
| `sn_awh_config.gateway_access_control_enabled` | `false` | Client access policies are unavailable until this is turned on |

The gateway "is set up to block calls" to an inactive tool ([Controlling which tools clients can access][aigw-client-access]). We do not know how the scan rates this server's tools. A tool it flags stops answering through the gateway while nothing changes on this server, which never sees the blocked calls. So look at the server record's **Tools** sub-tab after onboarding and after each upgrade of this server: a release can change a tool description, and [contract.json](contract.json) holds the descriptions a client receives.

### Data Sensitivity Check, and credential-type system properties

The Data Sensitivity Check "helps filter personally identifiable information in MCP traffic" ([AI Gateway Policies tab][aigw-policies-tab]). When it is enabled for a server it "prevents sensitive data from passing between AI agents and the MCP server" ([Managing your AI Gateway][aigw-manage]). Its switch for all servers is on by default. It applies to a tool only when it is also active for that server and for that tool. The documentation does not say whether a newly approved server starts active, whether a flagged result is masked or blocked, or whether a credential counts as sensitive data.

Do not count on it to cover the following. **As of 0.9.3, the current release, this server can return the values of credential-type system properties (`password` and `password2`) when the identity is an admin.** `get_system_properties`, and `list_records` or `get_record` on `sys_properties`, pass on what the Table API returns for those rows, unmasked. A fix is planned for the next release. Until then the identity rule above is the protection: reading `sys_properties` needs `admin`, and without it `get_system_properties` returns an empty list ([roles](tools.md#roles)).

### Entitlements and where the gateway is unavailable

- **What ServiceNow lists as prerequisites:** a Now Assist subscription, the "AI Control Tower for Now Assist – Pro Plus" licence, AI Agent Studio, and the plugins `sn_ai_governance` 5.0.6 or later and `sn_telemetry_data` 1.1.10 or later ([AI Gateway][aigw-overview], a page from 2026-09-10 filed under the legacy AI Control Tower section). The newer setup page says that activating AI Control Tower installs the plugin that provides the gateway, `sn_awh_config` ([Configuring AI Gateway][aigw-configuring]).
- **Domain separation:** "AI Gateway isn't available on instances that use domain separation" ([Configuring AI Gateway][aigw-configuring]).
- **Restricted environments:** the gateway's landing page carries ServiceNow's general notice that some AI features are unavailable in the FedRAMP, NSC DOD IL5 and Australia IRAP-Protected data centers, for self-hosted customers and in Regulated Markets. It does not say which features ([AI Gateway in AI Control Tower][aigw-landing]).
- **Developer instances:** the documentation does not mention them. A free developer instance does not come with the entitlements above, and the one we checked on 2026-11-08 did not route `/sncapps` paths at all. This is our observation, not ServiceNow's statement.
- **Where the data goes:** the same landing page says the application "requires data to be transferred from ServiceNow customers' individual instances to a centralized ServiceNow environment", possibly in another region or at a third-party cloud provider, and that ServiceNow collects the application's inputs and outputs unless the customer opts out. Tool results from this server pass through the gateway, so read that page before you send records through it. Where records must stay put, connect clients to this server directly.

### Not tested

We have tested none of the following. All but the last need a licensed AI Control Tower instance:

- the flow end to end: registration, this server's consent page and the ServiceNow sign-in through the gateway;
- whether AI Control Tower accepts a DCR answer that has no client secret;
- how variants map to ServiceNow identities;
- the scan result for this server's tools (13 with `--read-only`, 20 without);
- what the Data Sensitivity Check does to this server's results;
- whether resources, the `skill://` resources among them, and the server instructions reach an agent: the gateway pages describe tools only;
- the MCP protocol version the gateway speaks to a server;
- whether the gateway forwards a client identity or trace headers;
- whether a user flagged *Web service access only*, as the [recommended integration identity](configuration.md#recommended-integration-identity) is, can complete the browser sign-in that the authorization code grant needs.

If you run this server behind AI Gateway, please [open an issue](https://github.com/jschuller/mcp-server-servicenow/issues) with what you find.

### Sources for this section

ServiceNow's documentation as published in the [ServiceNowDocs](https://github.com/ServiceNow/ServiceNowDocs) repository (Apache-2.0), branch `brazil`, commit `47ad405f75bb` ("Brazil GA release", 2026-11-06). Each row gives the page, its file at that commit, the file's blob id and the page's own last-updated date.

| Page | Source at `47ad405f75bb` | Blob | Updated |
|---|---|---|---|
| [Managing MCP server records](https://www.servicenow.com/docs/r/brazil/intelligent-experiences/managing-mcp-server-details.html) | [managing-mcp-server-details.md][aigw-record] | `e6e3fbd296b3` | 2026-09-10 |
| [Connecting agents through AI Gateway](https://www.servicenow.com/docs/r/brazil/intelligent-experiences/ai-gw-connecting-agents.html) | [ai-gw-connecting-agents.md][aigw-connect] | `5ff9e07e0603` | 2026-10-23 |
| [Add an MCP server from AI Control Tower](https://www.servicenow.com/docs/r/brazil/intelligent-experiences/aict-add-an-mcp-server-from-ai-control-tower.html) | [aict-add-an-mcp-server-from-ai-control-tower.md][aigw-intake] | `aca789f89e38` | 2026-09-10 |
| [Add an MCP server from MCP Catalog](https://www.servicenow.com/docs/r/brazil/intelligent-experiences/aict-add-an-mcp-server-from-mcp-catalog.html) | [aict-add-an-mcp-server-from-mcp-catalog.md][aigw-catalog] | `3b8ede941c5a` | 2026-09-09 |
| [Exploring AI Gateway](https://www.servicenow.com/docs/r/brazil/intelligent-experiences/ai-gw-exploring.html) | [ai-gw-exploring.md][aigw-exploring] | `2460e8df5c7d` | 2026-10-22 |
| [AI Gateway Overview tab](https://www.servicenow.com/docs/r/brazil/intelligent-experiences/ai-gw-overview-tab.html) | [ai-gw-overview-tab.md][aigw-overview-tab] | `fce3c0945c0b` | 2026-10-22 |
| [Controlling which tools clients can access](https://www.servicenow.com/docs/r/brazil/intelligent-experiences/ai-gw-controlling-client-access.html) | [ai-gw-controlling-client-access.md][aigw-client-access] | `161fb61db41d` | 2026-10-26 |
| [Managing your AI Gateway](https://www.servicenow.com/docs/r/brazil/intelligent-experiences/managing-your-ai-gateway.html) | [managing-your-ai-gateway.md][aigw-manage] | `611f4ab5a959` | 2026-09-10 |
| [AI Gateway roles and system properties](https://www.servicenow.com/docs/r/brazil/intelligent-experiences/ai-gw-roles-properties.html) | [ai-gw-roles-properties.md][aigw-properties] | `41d4b349ad77` | 2026-10-22 |
| [AI Gateway Tools tab](https://www.servicenow.com/docs/r/brazil/intelligent-experiences/ai-gw-tools-tab.html) | [ai-gw-tools-tab.md][aigw-tools-tab] | `ad1f058612a0` | 2026-10-22 |
| [AI Gateway Policies tab](https://www.servicenow.com/docs/r/brazil/intelligent-experiences/ai-gw-policies-tab.html) | [ai-gw-policies-tab.md][aigw-policies-tab] | `f3e5f566162d` | 2026-10-22 |
| [AI Gateway](https://www.servicenow.com/docs/r/brazil/intelligent-experiences/ai-control-tower/ai-gateway-overview.html) | [ai-control-tower/ai-gateway-overview.md][aigw-overview] | `7f07f4f35338` | 2026-09-10 |
| [Configuring AI Gateway](https://www.servicenow.com/docs/r/brazil/intelligent-experiences/ai-gw-configuring.html) | [ai-gw-configuring.md][aigw-configuring] | `064e2cc6a2b0` | 2026-10-22 |
| [AI Gateway in AI Control Tower](https://www.servicenow.com/docs/r/brazil/intelligent-experiences/ai-gw-landing.html) | [ai-gw-landing.md][aigw-landing] | `c42eb62d5fe4` | 2026-10-22 |

[aigw-record]: https://github.com/ServiceNow/ServiceNowDocs/blob/47ad405f75bb/markdown/intelligent-experiences/managing-mcp-server-details.md
[aigw-connect]: https://github.com/ServiceNow/ServiceNowDocs/blob/47ad405f75bb/markdown/intelligent-experiences/ai-gw-connecting-agents.md
[aigw-intake]: https://github.com/ServiceNow/ServiceNowDocs/blob/47ad405f75bb/markdown/intelligent-experiences/aict-add-an-mcp-server-from-ai-control-tower.md
[aigw-catalog]: https://github.com/ServiceNow/ServiceNowDocs/blob/47ad405f75bb/markdown/intelligent-experiences/aict-add-an-mcp-server-from-mcp-catalog.md
[aigw-exploring]: https://github.com/ServiceNow/ServiceNowDocs/blob/47ad405f75bb/markdown/intelligent-experiences/ai-gw-exploring.md
[aigw-overview-tab]: https://github.com/ServiceNow/ServiceNowDocs/blob/47ad405f75bb/markdown/intelligent-experiences/ai-gw-overview-tab.md
[aigw-client-access]: https://github.com/ServiceNow/ServiceNowDocs/blob/47ad405f75bb/markdown/intelligent-experiences/ai-gw-controlling-client-access.md
[aigw-manage]: https://github.com/ServiceNow/ServiceNowDocs/blob/47ad405f75bb/markdown/intelligent-experiences/managing-your-ai-gateway.md
[aigw-properties]: https://github.com/ServiceNow/ServiceNowDocs/blob/47ad405f75bb/markdown/intelligent-experiences/ai-gw-roles-properties.md
[aigw-tools-tab]: https://github.com/ServiceNow/ServiceNowDocs/blob/47ad405f75bb/markdown/intelligent-experiences/ai-gw-tools-tab.md
[aigw-policies-tab]: https://github.com/ServiceNow/ServiceNowDocs/blob/47ad405f75bb/markdown/intelligent-experiences/ai-gw-policies-tab.md
[aigw-overview]: https://github.com/ServiceNow/ServiceNowDocs/blob/47ad405f75bb/markdown/intelligent-experiences/ai-control-tower/ai-gateway-overview.md
[aigw-configuring]: https://github.com/ServiceNow/ServiceNowDocs/blob/47ad405f75bb/markdown/intelligent-experiences/ai-gw-configuring.md
[aigw-landing]: https://github.com/ServiceNow/ServiceNowDocs/blob/47ad405f75bb/markdown/intelligent-experiences/ai-gw-landing.md
