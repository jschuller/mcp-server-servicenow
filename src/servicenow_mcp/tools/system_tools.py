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
            description="Comma-separated fields to return (default: user_name,name,email,roles)"
        ),
    ] = None,
) -> Dict[str, Any]:
    """Get the currently authenticated user's information"""
    config = get_config()

    # Try the UI endpoint first (works with basic auth)
    url = f"{config.instance_url}/api/now/ui/user/current_user"
    try:
        response = make_sn_request("GET", url, config.timeout)
        data = parse_json_response(response, url)
        return data.get("result", {})
    except Exception:
        pass

    # Fallback: query sys_user via Table API (works with all auth types including OAuth).
    # Server-authored query — not subject to the caller-query javascript: policy.
    table_url = build_url(config.api_url, "table", "sys_user")
    params: Dict[str, Any] = {
        "sysparm_query": "user_name=javascript:gs.getUserName()",
        "sysparm_limit": 1,
        "sysparm_fields": fields or "user_name,name,email,sys_id,roles",
    }
    response = make_sn_request("GET", table_url, config.timeout, params=params)
    data = parse_json_response(response, table_url)
    results = data.get("result", [])
    if results:
        user = results[0]
        return {
            "user_name": user.get("user_name"),
            "user_display_name": user.get("name"),
            "user_email": user.get("email"),
            "user_sys_id": user.get("sys_id"),
            "roles": user.get("roles"),
        }
    return {}


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
