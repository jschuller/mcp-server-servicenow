"""ServiceNow CMDB tools.

Provides operations on CMDB configuration items via the Table API.
"""

import logging
from typing import Annotated, Any, Dict, Optional

from pydantic import Field

from servicenow_mcp.server import mcp, get_config, get_auth_manager
from servicenow_mcp.utils.http import api_request, parse_json_response

logger = logging.getLogger(__name__)


@mcp.tool()
def list_ci(
    class_name: Annotated[str, Field(description="CMDB class name (e.g., 'cmdb_ci', 'cmdb_ci_server', 'cmdb_ci_computer')")] = "cmdb_ci",
    query: Annotated[Optional[str], Field(description="Encoded query string (e.g., 'operational_status=1')")] = None,
    fields: Annotated[Optional[str], Field(description="Comma-separated list of fields to return")] = None,
    limit: Annotated[int, Field(ge=1, le=1000, description="Maximum number of CIs to return")] = 20,
    offset: Annotated[int, Field(ge=0, description="Number of records to skip")] = 0,
) -> Dict[str, Any]:
    """List CMDB configuration items with optional class and query filtering"""
    config = get_config()
    auth_manager = get_auth_manager()

    url = f"{config.api_url}/table/{class_name}"
    query_params: Dict[str, Any] = {
        "sysparm_limit": limit,
        "sysparm_offset": offset,
    }
    if query:
        query_params["sysparm_query"] = query
    if fields:
        query_params["sysparm_fields"] = fields

    response = api_request("GET", url, auth_manager, config.timeout, params=query_params)
    data = parse_json_response(response, url)
    result = data.get("result", [])
    return {"count": len(result), "class": class_name, "records": result}


@mcp.tool()
def get_ci(
    sys_id: Annotated[str, Field(description="The sys_id of the CI")],
    class_name: Annotated[str, Field(description="CMDB class name")] = "cmdb_ci",
) -> Dict[str, Any]:
    """Get a single CMDB configuration item by sys_id"""
    config = get_config()
    auth_manager = get_auth_manager()

    url = f"{config.api_url}/table/{class_name}/{sys_id}"
    response = api_request("GET", url, auth_manager, config.timeout)
    data = parse_json_response(response, url)
    return data.get("result", {})


@mcp.tool()
def create_ci(
    data: Annotated[Dict[str, Any], Field(description="CI attributes as key-value pairs (must include 'name')")],
    class_name: Annotated[str, Field(description="CMDB class name")] = "cmdb_ci",
) -> Dict[str, Any]:
    """Create a new CMDB configuration item"""
    config = get_config()
    auth_manager = get_auth_manager()

    url = f"{config.api_url}/table/{class_name}"
    response = api_request("POST", url, auth_manager, config.timeout, json_data=data)
    resp_data = parse_json_response(response, url)
    result = resp_data.get("result", {})
    return {"sys_id": result.get("sys_id"), "record": result}


@mcp.tool()
def update_ci(
    sys_id: Annotated[str, Field(description="The sys_id of the CI to update")],
    data: Annotated[Dict[str, Any], Field(description="CI attributes to update")],
    class_name: Annotated[str, Field(description="CMDB class name")] = "cmdb_ci",
) -> Dict[str, Any]:
    """Update a CMDB configuration item"""
    config = get_config()
    auth_manager = get_auth_manager()

    url = f"{config.api_url}/table/{class_name}/{sys_id}"
    response = api_request("PATCH", url, auth_manager, config.timeout, json_data=data)
    resp_data = parse_json_response(response, url)
    result = resp_data.get("result", {})
    return {"sys_id": result.get("sys_id"), "record": result}


@mcp.tool()
def get_ci_relationships(
    sys_id: Annotated[str, Field(description="The sys_id of the CI")],
    relation_type: Annotated[Optional[str], Field(description="Filter by relationship type sys_id")] = None,
) -> Dict[str, Any]:
    """Get relationships for a CMDB configuration item (parent and child)"""
    config = get_config()
    auth_manager = get_auth_manager()

    url = f"{config.api_url}/table/cmdb_rel_ci"
    query = f"parent={sys_id}^ORchild={sys_id}"
    if relation_type:
        query += f"^type={relation_type}"

    query_params = {
        "sysparm_query": query,
        "sysparm_limit": 100,
    }

    response = api_request("GET", url, auth_manager, config.timeout, params=query_params)
    data = parse_json_response(response, url)
    result = data.get("result", [])
    return {"count": len(result), "relationships": result}
