# Privacy

mcp-server-servicenow is an open-source program that runs on your machine (or on a server you deploy). Its maintainer runs no service behind it and receives none of your data.

## What the server sends, and where

- **Only to your ServiceNow instance.** Every request goes to the instance in `SERVICENOW_INSTANCE_URL`: the Table, Stats, CMDB and schema APIs, and the instance's own OAuth token endpoint when you use OAuth. Nothing goes to the maintainer or to any other service.
- **Your credentials stay with you.** The server reads them from its environment at start, sends them only to that instance, and never writes them to disk or to its logs.
- **No telemetry, no analytics, no update checks.** FastMCP, the framework the server is built on, includes OpenTelemetry hooks that export nothing unless you install and configure an exporter yourself.

## What it keeps

- **Nothing between runs** on your machine. An OAuth token is held in memory while the process runs. A shared HTTP deployment with OAuth keeps its users' tokens in FastMCP's encrypted token storage on that server ([deployment](deployment.md)).
- **An audit log**, unless you turn it off: one JSON line per tool call or resource read, with the tool, the table, the record's sys_id, the encoded query (password-, secret- and token-like values masked, length capped), the names of the fields written but not their values, the outcome and the duration. Credentials never appear in it. It goes to stderr by default (your MCP client decides whether to keep it), to a file you name, or nowhere (`SERVICENOW_AUDIT_LOG=off`). See [configuration](configuration.md).

## What your AI client does with the results

Records the server reads are returned to your MCP client (Claude Code, Claude Desktop, VS Code and others), which passes them to the model you use. That client's and model provider's own privacy terms cover what happens next. Use a read-only identity and the least roles your work needs ([configuration](configuration.md)), and point the server at instances whose data you are allowed to share with that provider.

## Installing it

`uvx` downloads the package and its dependencies from PyPI, which sees the download like any other. The Claude Code plugin does the same and pins the exact version.

## Questions

Ask in [Discussions](https://github.com/jschuller/mcp-server-servicenow/discussions/categories/q-a), or report a security problem privately as [SECURITY.md](../SECURITY.md) describes.
