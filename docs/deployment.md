# Deployment Guide

## Docker / Cloud Run

```bash
# Build
docker build -t mcp-server-servicenow .

# Run locally
# The server fails closed: an HTTP listener requires MCP endpoint auth
# (MCP_STATIC_TOKENS or MCP_OAUTH_*), otherwise it exits at startup.
docker run -p 8080:8080 \
  -e SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com \
  -e SERVICENOW_AUTH_TYPE=basic \
  -e SERVICENOW_USERNAME=admin \
  -e SERVICENOW_PASSWORD=your-password \
  -e MCP_STATIC_TOKENS=a-long-random-token \
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
  --set-env-vars "MCP_STATIC_TOKENS=..." \
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

## Verify HTTP Transport

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
| **HTTP + static tokens** | Bearer tokens (`MCP_STATIC_TOKENS`) | Global creds (env vars) | CI/CD, development |
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
