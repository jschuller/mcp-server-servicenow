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
