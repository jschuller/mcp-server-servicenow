# Alongside ServiceNow's own MCP servers

ServiceNow ships MCP servers of its own: the **MCP Server Console** (Action Fabric, the `sn_mcp_server` app), where an admin publishes Now Assist skills, flows, scripted REST APIs and playbooks as governed tools, and **pre-built servers** for ITSM, ITOM, CMDB and SPM, announced as generally available for Claude, Copilot and Gemini on [2026-09-10](https://www.servicenow.com/community/itsm-blog/servicenow-launches-out-of-the-box-mcp-servers-for-claude/ba-p/3596376). They answer outcome-shaped questions ("summarize this change") with ServiceNow's own logic and governance.

This project is the other half: the developer loop. It reads and writes any table through the Table API, reads the data dictionary, aggregates with the Stats API and works with update sets — on any release from Tokyo up, on a free developer instance, under the MIT licence. ServiceNow's own CEG AI CoE guide lists `uvx mcp-server-servicenow` as its community "Path C".

| | ServiceNow MCP Server Console and pre-built servers | This project |
|---|---|---|
| **Tool sources** | Now Assist skills, Knowledge Graph, subflows/actions, scripted REST (GET/POST/PUT), playbooks, MCP Apps; pre-built ITSM / ITOM / CMDB / SPM tools | Table API CRUD, Stats API aggregates, `sys_dictionary` schema, update sets, CMDB via the Table API |
| **Table API** | Not a tool source in the Console ("cannot be converted to MCP tools regardless of configuration", KB2952534) | Any table, any field |
| **Minimum release** | Zurich P9 / Australia P2 for custom tools | Tokyo+ |
| **Entitlement** | Now Assist / AI-native SKU; metered in assists | MIT, $0, your own compute |
| **Developer instances (PDIs)** | Not available as of July 2026 | Works |
| **Auth** | OAuth 2.0 auth-code via Machine Identity Console | Basic, OAuth (client credentials or password grant), API key; over HTTP an OAuth 2.1 + PKCE proxy (DCR + CIMD) |
| **Governance** | AI Control Tower / AI Gateway | Self-managed: `--read-only`, query validation, JSON audit log, tool annotations; table scope from ServiceNow ACLs |
| **Transport** | Streamable HTTP | stdio + Streamable HTTP |
| **Resources / skills / prompts** | Roadmap | 5 resources; 4 Agent Skills as `skill://` resources (SEP-2640); prompts planned |

The Console rows were checked against ServiceNow's documentation, KB2952534 and the AI Academy material on 2026-08-22. The pre-built servers' announcement does not state their entitlement, minimum release or PDI availability, so those cells describe the Console; check your instance before relying on them.

## Run both

The two answer different questions. ServiceNow's servers tell the model what ServiceNow *means* — skills, summaries, governed outcomes. This server tells it what ServiceNow *contains* — rows, schema, aggregates, update sets. Register both in your client under different names (for example `servicenow` and `servicenow-native`), and let the model pick per question. When both can answer, prefer ServiceNow's tool for a governed outcome and this one for raw data, schema and update-set review.
