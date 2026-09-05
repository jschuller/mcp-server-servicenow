# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it responsibly.

**Do NOT open a public GitHub issue for security vulnerabilities.**

Instead, please email the maintainer directly or use [GitHub's private vulnerability reporting](https://github.com/jschuller/mcp-server-servicenow/security/advisories/new).

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
| 0.7.x   | Yes       |
| < 0.7   | No        |

## Security Best Practices

When using this MCP server:

- **Never commit credentials** — Use environment variables or `.env` files (gitignored)
- **Use OAuth 2.1 + PKCE** for production deployments (see [Deployment Guide](docs/deployment.md))
- **Restrict ServiceNow user roles** — Create a dedicated integration user with minimal permissions
- **Use GCP IAM** when deploying to Cloud Run without OAuth proxy
