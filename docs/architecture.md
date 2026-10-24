# Architecture

```mermaid
graph TD
    CC["MCP Client"]
    subgraph SERVER["FastMCP 4"]
        TT["table_tools (6)"]
        CT["cmdb_tools (5)"]
        ST["system_tools (4)"]
        UT["update_set_tools (5)"]
        RS["resources (5)"]
        SK["skills (4)"]
        SNR["make_sn_request"]
    end
    subgraph AUTH["Auth + HTTP"]
        AM["auth_manager"]
        AR["api_request"]
    end
    SN["ServiceNow Instance"]

    CC -->|"stdio / Streamable HTTP"| SERVER
    TT --> SNR
    CT --> SNR
    ST --> SNR
    UT --> SNR
    RS --> SNR
    SNR --> AR
    AM -.->|"credentials"| AR
    AR -->|"REST API"| SN
```

Built with [FastMCP 4](https://gofastmcp.com): it speaks both the stateless MCP 2026-07-28 protocol and the legacy handshake, negotiated per connection.

## Mounting it in your own server

The server is a building block: mount it into your own FastMCP server and it keeps its read-only mode, identifier and query validation and audit log. FastMCP does not forward a mounted server's instructions and prefixes its URIs, so pass the rendered ones on:

```python
from fastmcp import FastMCP
from servicenow_mcp.server import mcp as servicenow, init_services, render_instructions
from servicenow_mcp.utils.config import ServerConfig

SKILLS = True  # False: no skill:// resources and no skill part in the instructions
init_services(ServerConfig(..., skills=SKILLS))  # your instance and auth

# The tools and resources register when their modules are imported, so import them
# after init_services(), as cli.main() does; resources reads the switch once, here.
import servicenow_mcp.tools.table_tools  # noqa: E402,F401
import servicenow_mcp.tools.cmdb_tools  # noqa: E402,F401
import servicenow_mcp.tools.system_tools  # noqa: E402,F401
import servicenow_mcp.tools.update_set_tools  # noqa: E402,F401
import servicenow_mcp.resources  # noqa: E402,F401

app = FastMCP("orchestrator", instructions=render_instructions("snow", skills=SKILLS))
app.mount(servicenow, namespace="snow")  # tools snow_*, resources servicenow://snow/…, skill://snow/…
```
