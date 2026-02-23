"""ServiceNow system tools.

Provides system information and property queries.
"""

import logging
from typing import Annotated, Any, Dict, Optional

from pydantic import Field

from servicenow_mcp.server import mcp, get_config, get_auth_manager
from servicenow_mcp.utils.http import api_request, parse_json_response

logger = logging.getLogger(__name__)


@mcp.tool()
def get_system_properties(
    query: Annotated[Optional[str], Field(description="Filter query (e.g., 'name=glide.servlet.uri' or 'nameLIKEglide')")] = None,
    limit: Annotated[int, Field(ge=1, le=100, description="Maximum number of properties to return")] = 20,
) -> Dict[str, Any]:
    """Query ServiceNow system properties"""
    config = get_config()
    auth_manager = get_auth_manager()

    url = f"{config.api_url}/table/sys_properties"
    query_params: Dict[str, Any] = {
        "sysparm_limit": limit,
        "sysparm_fields": "name,value,description",
    }
    if query:
        query_params["sysparm_query"] = query

    response = api_request("GET", url, auth_manager, config.timeout, params=query_params)
    data = parse_json_response(response, url)
    result = data.get("result", [])
    return {"count": len(result), "properties": result}


@mcp.tool()
def get_current_user(
    fields: Annotated[Optional[str], Field(description="Comma-separated fields to return (default: user_name,name,email,roles)")] = None,
) -> Dict[str, Any]:
    """Get the currently authenticated user's information"""
    config = get_config()
    auth_manager = get_auth_manager()

    url = f"{config.instance_url}/api/now/ui/user/current_user"
    response = api_request("GET", url, auth_manager, config.timeout)
    data = parse_json_response(response, url)
    return data.get("result", {})


@mcp.tool()
def get_table_schema(
    table_name: Annotated[str, Field(description="The table name to get schema for")],
    limit: Annotated[int, Field(ge=1, le=500, description="Maximum number of fields to return")] = 50,
) -> Dict[str, Any]:
    """Get the data dictionary (field definitions) for a ServiceNow table"""
    config = get_config()
    auth_manager = get_auth_manager()

    url = f"{config.api_url}/table/sys_dictionary"
    query_params = {
        "sysparm_query": f"name={table_name}^internal_type!=collection",
        "sysparm_fields": "element,column_label,internal_type,max_length,mandatory,reference",
        "sysparm_limit": limit,
    }

    response = api_request("GET", url, auth_manager, config.timeout, params=query_params)
    data = parse_json_response(response, url)
    result = data.get("result", [])
    fields_list = [
        {
            "name": r.get("element"),
            "label": r.get("column_label"),
            "type": r.get("internal_type"),
            "max_length": r.get("max_length"),
            "mandatory": r.get("mandatory"),
            "reference": r.get("reference"),
        }
        for r in result
        if r.get("element")
    ]
    return {"table": table_name, "field_count": len(fields_list), "fields": fields_list}
