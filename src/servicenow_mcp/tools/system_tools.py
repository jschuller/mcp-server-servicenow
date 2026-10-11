"""ServiceNow system tools.

Provides system information and property queries.
"""

import logging
from typing import Annotated, Any, Dict, Optional

from pydantic import Field

from servicenow_mcp.server import mcp, get_config, make_sn_request
from servicenow_mcp.tools import annotations
from servicenow_mcp.utils.http import build_url, parse_json_response
from servicenow_mcp.utils.schema import fetch_table_schema
from servicenow_mcp.utils.user import fetch_current_user

logger = logging.getLogger(__name__)


@mcp.tool(tags={"read", "admin"}, annotations=annotations.READ)
def get_system_properties(
    query: Annotated[
        Optional[str],
        Field(
            description="Filter query (e.g., 'name=glide.servlet.uri' or 'nameLIKEglide')"
        ),
    ] = None,
    limit: Annotated[
        int, Field(ge=1, le=100, description="Maximum number of properties to return")
    ] = 20,
) -> Dict[str, Any]:
    """Query ServiceNow system properties"""
    config = get_config()

    url = build_url(config.api_url, "table", "sys_properties")
    query_params: Dict[str, Any] = {
        "sysparm_limit": limit,
        "sysparm_fields": "name,value,description",
    }
    if query:
        query_params["sysparm_query"] = query

    response = make_sn_request("GET", url, config.timeout, params=query_params)
    data = parse_json_response(response, url)
    result = data.get("result", [])
    return {"count": len(result), "properties": result}


@mcp.tool(tags={"read", "admin"}, annotations=annotations.READ)
def get_current_user(
    fields: Annotated[
        Optional[str],
        Field(
            description="Extra sys_user fields to return besides user_name, user_display_name, user_email, user_sys_id and roles"
        ),
    ] = None,
) -> Dict[str, Any]:
    """Get the authenticated user's identity and directly assigned, active roles"""
    config = get_config()
    return fetch_current_user(config.api_url, config.timeout, fields)


@mcp.tool(tags={"read", "admin"}, annotations=annotations.READ)
def get_table_schema(
    table_name: Annotated[str, Field(description="The table name to get schema for")],
    limit: Annotated[
        int,
        Field(
            ge=1,
            le=1000,
            description="Maximum number of fields to return (own fields first, then inherited)",
        ),
    ] = 200,
    include_inherited: Annotated[
        bool,
        Field(
            description="Include fields inherited from parent tables (e.g. task fields on incident)"
        ),
    ] = True,
) -> Dict[str, Any]:
    """Get the data dictionary (field definitions) for a ServiceNow table, including inherited fields"""
    config = get_config()
    return fetch_table_schema(
        table_name,
        limit=limit,
        timeout=config.timeout,
        api_url=config.api_url,
        include_inherited=include_inherited,
    )
