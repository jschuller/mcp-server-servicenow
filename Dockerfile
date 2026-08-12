FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install --no-cache-dir .
EXPOSE 8080
# The container boundary provides the isolation, so bind all interfaces
# inside it (the CLI default of 127.0.0.1 would be unreachable from the
# host/Cloud Run). The server still fails closed: it refuses to start an
# HTTP listener unless MCP endpoint auth is configured — set MCP_OAUTH_*
# (OAuth 2.1 + PKCE) or MCP_STATIC_TOKENS at run time.
ENV MCP_HOST=0.0.0.0
CMD ["mcp-server-servicenow", "--transport", "streamable-http", "--port", "8080"]
