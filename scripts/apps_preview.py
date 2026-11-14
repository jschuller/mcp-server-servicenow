"""Preview the MCP Apps views without an instance: the real tool and view, made-up data.

    uv run --frozen --extra dev --with 'prefab-ui>=0.18.0' \
      fastmcp dev apps scripts/apps_preview.py --no-reload

FastMCP's local host (the official ext-apps AppBridge) lists the app tools and
renders the one you launch; any update_set_sys_id of letters and digits works.
One row carries markup in its text, to show that the view displays it as text.
See docs/apps.md.
"""

import json
from unittest.mock import Mock

from fastmcp import FastMCP

from servicenow_mcp import apps
from servicenow_mcp.server import init_services
from servicenow_mcp.utils.config import (
    AuthConfig,
    AuthType,
    BasicAuthConfig,
    ServerConfig,
)

init_services(
    ServerConfig(
        instance_url="https://example.invalid",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="preview", password="preview"),
        ),
    )
)

HEADER = {
    "sys_id": "a" * 32,
    "name": "REL-12 Incident routing fixes",
    "state": "complete",
    "description": "Routing rules for the network team, a form tidy-up and one retired client script.",
    "application.name": "Global",
    "sys_created_by": "dev.one",
    "sys_created_on": "2026-11-01 09:00:00",
    "sys_updated_on": "2026-11-10 17:30:00",
}
ROWS = [
    (
        "Business Rule",
        "Set assignment group from CI",
        "INSERT_OR_UPDATE",
        "dev.one",
        "2026-11-10 17:30:00",
        "sys_script",
    ),
    (
        "Business Rule",
        "Escalate P1 after 30 minutes",
        "INSERT_OR_UPDATE",
        "dev.one",
        "2026-11-10 16:02:11",
        "sys_script",
    ),
    (
        "Script Include",
        "IncidentRoutingUtil",
        "INSERT_OR_UPDATE",
        "dev.two",
        "2026-11-10 11:44:53",
        "sys_script_include",
    ),
    (
        "Client Script",
        "Hide legacy category",
        "DELETE",
        "dev.two",
        "2026-11-09 08:15:00",
        "sys_script_client",
    ),
    (
        "Client Script",
        "<img src=x onerror=alert(1)> Validate caller",
        "INSERT_OR_UPDATE",
        "dev.two",
        "2026-11-09 08:01:40",
        "sys_script_client",
    ),
    (
        "UI Policy",
        "Require CI on network incidents",
        "INSERT_OR_UPDATE",
        "dev.one",
        "2026-11-08 15:20:09",
        "sys_ui_policy",
    ),
    (
        "Dictionary",
        "Incident.u_routing_reason",
        "INSERT_OR_UPDATE",
        "dev.one",
        "2026-11-07 10:12:31",
        "sys_dictionary",
    ),
    (
        "Form Layout",
        "Incident [Default view]",
        "INSERT_OR_UPDATE",
        "dev.three",
        "2026-11-07 09:58:02",
        "sys_ui_form",
    ),
    (
        "Access Control",
        "incident.u_routing_reason (write)",
        "INSERT_OR_UPDATE",
        "dev.one",
        "2026-11-06 14:40:27",
        "sys_security_acl",
    ),
    (
        "System Property",
        "x.routing.default_group",
        "INSERT_OR_UPDATE",
        "dev.three",
        "2026-11-05 13:05:18",
        "sys_properties",
    ),
    (
        "Business Rule",
        "Old auto-assign (retired)",
        "DELETE",
        "dev.one",
        "2026-11-05 12:59:44",
        "sys_script",
    ),
    (
        "Script Include",
        "RoutingTableCache",
        "INSERT_OR_UPDATE",
        "dev.two",
        "2026-11-04 16:31:05",
        "sys_script_include",
    ),
]
CHANGES = [
    {
        "sys_id": f"{i:032x}",
        "name": f"{table}_{i:032x}",
        "type": kind,
        "target_name": target,
        "action": action,
        "sys_created_by": who,
        "sys_updated_on": when,
    }
    for i, (kind, target, action, who, when, table) in enumerate(ROWS, start=1)
]


def fake_request(method, url, timeout=30, params=None, json_data=None):
    assert method == "GET"
    limit = (params or {}).get("sysparm_limit", len(CHANGES))
    payload = (
        {"result": CHANGES[:limit]}
        if url.endswith("/sys_update_xml")
        else {"result": HEADER}
    )
    response = Mock()
    response.status_code = 200
    response.text = json.dumps(payload)
    response.headers = {"Content-Type": "application/json"}
    response.json.return_value = payload
    return response


apps.make_sn_request = fake_request

mcp = FastMCP("servicenow-apps-preview")
apps.register_apps(mcp)
