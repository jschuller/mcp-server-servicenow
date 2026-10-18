# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it responsibly.

**Do NOT open a public GitHub issue for security vulnerabilities.**

Instead, use [GitHub's private vulnerability reporting](https://github.com/jschuller/mcp-server-servicenow/security/advisories/new), which reaches the maintainer privately. If that page says private reporting is unavailable, open a [Discussion](https://github.com/jschuller/mcp-server-servicenow/discussions/categories/q-a) titled "Security contact request" with no details, and the maintainer will reply with a private channel.

### What to include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### Response timeline

- **Acknowledgment**: Within 48 hours
- **Assessment**: Within 1 week
- **Fix**: Depending on severity, typically within 2 weeks

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.9.x   | Yes       |
| < 0.9   | No        |

Fixes ship in the latest release only. The table moves with each minor release ([RELEASING.md](RELEASING.md), pre-flight 1).

## Security Best Practices

When using this MCP server:

- **Never commit credentials** — Use environment variables or `.env` files (gitignored)
- **Use OAuth 2.1 + PKCE** for production deployments (see [Deployment Guide](docs/deployment.md))
- **Restrict ServiceNow user roles** — Create a dedicated integration user with minimal permissions
- **Use GCP IAM** when deploying to Cloud Run without OAuth proxy
