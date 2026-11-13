"""MCP Apps views (SEP-1865, extension ``io.modelcontextprotocol/ui``): a spike.

An MCP App is two ordinary MCP objects: a tool, and an HTML resource under
``ui://`` that the tool names in ``_meta.ui.resourceUri``. A host that supports
the extension renders the HTML in a sandboxed frame and hands it the tool's
result; any other host ignores the metadata and gets the same result as text.
So the view needs no separate fallback tool: it draws what the model reads.

Off by default (``--apps on``, ``ServerConfig.apps``). With it off nothing here
is registered, and the tool list, the resource list and
``docs/contract.json`` are unchanged.

One view so far, read-only:

- ``review_update_set`` + ``ui://servicenow/update-set-review.html``: an update
  set's header and its customer updates as a table the user can filter.

The HTML is one self-contained file: inline script and style, no network
access, so it runs under a host's default content security policy. It speaks
the view side of the protocol by hand (JSON-RPC over ``postMessage``) rather
than loading the ext-apps SDK from a CDN. Record text is untrusted: the view
writes it with ``textContent`` only.
"""

import logging
from importlib.resources import files
from typing import Annotated, Any, Dict, List

from fastmcp import FastMCP
from fastmcp.apps import AppConfig
from pydantic import Field
from typing_extensions import TypedDict

from servicenow_mcp.server import get_config, make_sn_request
from servicenow_mcp.tools.annotations import READ
from servicenow_mcp.tools.results import Row
from servicenow_mcp.utils.http import build_url, parse_json_response, result_rows

logger = logging.getLogger(__name__)

UPDATE_SET_REVIEW_URI = "ui://servicenow/update-set-review.html"
REVIEW_TOOL = "review_update_set"

# ``application.name`` dot-walks to the scope's name: stored values keep the
# dates in UTC, like list_update_set_changes, and still give a readable scope.
_HEADER_FIELDS = (
    "sys_id,name,state,description,application.name,"
    "sys_created_by,sys_created_on,sys_updated_on"
)
_CHANGE_FIELDS = "sys_id,name,type,target_name,action,sys_created_by,sys_updated_on"


class UpdateSetReview(TypedDict):
    update_set: Row
    count: int
    limit: int
    changes: List[Row]


def _view_html() -> str:
    return (
        files("servicenow_mcp.apps")
        .joinpath("update_set_review.html")
        .read_text(encoding="utf-8")
    )


def review_update_set(
    update_set_sys_id: Annotated[
        str,
        Field(
            description="The sys_id of the update set",
            pattern=r"^[A-Za-z0-9_]+$",
        ),
    ],
    limit: Annotated[
        int,
        Field(ge=1, le=200, description="Maximum number of changes to return"),
    ] = 100,
) -> UpdateSetReview:
    """Review one update set: its name, state and scope, and its customer updates
    (type, target, action, author), newest first. Read-only. Clients that support
    MCP Apps also show the result as a table the user can filter."""
    config = get_config()

    header_url = build_url(config.api_url, "table", "sys_update_set", update_set_sys_id)
    header_response = make_sn_request(
        "GET", header_url, config.timeout, params={"sysparm_fields": _HEADER_FIELDS}
    )
    header = parse_json_response(header_response, header_url).get("result", {})

    changes_url = build_url(config.api_url, "table", "sys_update_xml")
    params: Dict[str, Any] = {
        "sysparm_query": f"update_set={update_set_sys_id}^ORDERBYDESCsys_updated_on",
        "sysparm_fields": _CHANGE_FIELDS,
        "sysparm_limit": limit,
    }
    changes_response = make_sn_request(
        "GET", changes_url, config.timeout, params=params
    )
    changes = result_rows(parse_json_response(changes_response, changes_url))

    return {
        "update_set": header if isinstance(header, dict) else {},
        "count": len(changes),
        "limit": limit,
        "changes": changes,
    }


def register_apps(server: FastMCP) -> None:
    """Register the views and their tools on ``server`` (the CLI passes the singleton)."""
    server.resource(
        UPDATE_SET_REVIEW_URI,
        name="update-set-review",
        description=(
            "MCP Apps view for review_update_set: a filterable table of an "
            "update set's changes. Rendered by hosts that support MCP Apps."
        ),
        tags={"read", "updateset", "app"},
        app=AppConfig(prefers_border=True),
    )(_view_html)

    server.tool(
        name=REVIEW_TOOL,
        tags={"read", "updateset", "app"},
        annotations=READ,
        app=AppConfig(resource_uri=UPDATE_SET_REVIEW_URI),
    )(review_update_set)
