"""ServiceNow CMDB tools.

Provides operations on CMDB configuration items via the Table API.
"""

import logging
from typing import Annotated, Any, Dict, Optional

from pydantic import Field

from servicenow_mcp.server import get_config, make_sn_request, mcp
from servicenow_mcp.tools import annotations
from servicenow_mcp.tools.results import CIList, RelationshipList
from servicenow_mcp.tools.table_tools import (
    DisplayValue,
    ResponseFormat,
    display_value_params,
    drop_added_fields,
    fields_with_query_fields,
    list_warning,
    query_field_names,
    response_format_params,
)
from servicenow_mcp.utils.http import build_url, parse_json_response, result_rows

logger = logging.getLogger(__name__)


@mcp.tool(tags={"read", "cmdb"}, annotations=annotations.READ)
def list_ci(
    class_name: Annotated[
        str,
        Field(
            description="CMDB class name (e.g., 'cmdb_ci', 'cmdb_ci_server', 'cmdb_ci_computer')"
        ),
    ] = "cmdb_ci",
    query: Annotated[
        Optional[str],
        Field(description="Encoded query string (e.g., 'operational_status=1')"),
    ] = None,
    fields: Annotated[
        Optional[str], Field(description="Comma-separated list of fields to return")
    ] = None,
    limit: Annotated[
        int, Field(ge=1, le=1000, description="Maximum number of CIs to return")
    ] = 20,
    offset: Annotated[int, Field(ge=0, description="Number of records to skip")] = 0,
    response_format: ResponseFormat = "detailed",
    display_value: DisplayValue = "false",
) -> CIList:
    """List CMDB configuration items with optional class and query filtering"""
    config = get_config()

    url = build_url(config.api_url, "table", class_name)
    query_params: Dict[str, Any] = {
        "sysparm_limit": limit,
        "sysparm_offset": offset,
    }
    query_names, labels = query_field_names(query)
    sysparm_fields, added = fields_with_query_fields(fields, query_names)
    if query:
        query_params["sysparm_query"] = query
    if sysparm_fields:
        query_params["sysparm_fields"] = sysparm_fields
    query_params.update(response_format_params(response_format))
    query_params.update(display_value_params(display_value))

    response = make_sn_request("GET", url, config.timeout, params=query_params)
    data = parse_json_response(response, url)
    result = result_rows(data)
    warning = list_warning(class_name, fields, query_names, labels, result)
    drop_added_fields(result, added)
    payload: CIList = {"count": len(result), "class": class_name, "records": result}
    if warning:
        payload["warning"] = warning
    return payload


@mcp.tool(tags={"read", "cmdb"}, annotations=annotations.READ)
def get_ci(
    sys_id: Annotated[str, Field(description="The sys_id of the CI")],
    class_name: Annotated[str, Field(description="CMDB class name")] = "cmdb_ci",
    display_value: DisplayValue = "false",
) -> Dict[str, Any]:
    """Get a single CMDB configuration item by sys_id"""
    config = get_config()

    url = build_url(config.api_url, "table", class_name, sys_id)
    params = display_value_params(display_value)
    response = make_sn_request("GET", url, config.timeout, params=params or None)
    data = parse_json_response(response, url)
    return data.get("result", {})


@mcp.tool(tags={"write", "cmdb"}, annotations=annotations.CREATE)
def create_ci(
    data: Annotated[
        Dict[str, Any],
        Field(description="CI attributes as key-value pairs (must include 'name')"),
    ],
    class_name: Annotated[str, Field(description="CMDB class name")] = "cmdb_ci",
) -> Dict[str, Any]:
    """Create a new CMDB configuration item"""
    config = get_config()

    url = build_url(config.api_url, "table", class_name)
    response = make_sn_request("POST", url, config.timeout, json_data=data)
    resp_data = parse_json_response(response, url)
    result = resp_data.get("result", {})
    return {"sys_id": result.get("sys_id"), "record": result}


@mcp.tool(tags={"write", "cmdb"}, annotations=annotations.UPDATE)
def update_ci(
    sys_id: Annotated[str, Field(description="The sys_id of the CI to update")],
    data: Annotated[Dict[str, Any], Field(description="CI attributes to update")],
    class_name: Annotated[str, Field(description="CMDB class name")] = "cmdb_ci",
) -> Dict[str, Any]:
    """Update a CMDB configuration item"""
    config = get_config()

    url = build_url(config.api_url, "table", class_name, sys_id)
    response = make_sn_request("PATCH", url, config.timeout, json_data=data)
    resp_data = parse_json_response(response, url)
    result = resp_data.get("result", {})
    return {"sys_id": result.get("sys_id"), "record": result}


@mcp.tool(tags={"read", "cmdb"}, annotations=annotations.READ)
def get_ci_relationships(
    sys_id: Annotated[str, Field(description="The sys_id of the CI")],
    relation_type: Annotated[
        Optional[str], Field(description="Filter by relationship type sys_id")
    ] = None,
    limit: Annotated[
        int,
        Field(ge=1, le=1000, description="Maximum number of relationships to return"),
    ] = 100,
    offset: Annotated[
        int, Field(ge=0, description="Number of relationships to skip")
    ] = 0,
) -> RelationshipList:
    """Get relationships for a CMDB configuration item (parent and child)"""
    config = get_config()

    url = build_url(config.api_url, "table", "cmdb_rel_ci")
    query = f"parent={sys_id}^ORchild={sys_id}"
    if relation_type:
        query += f"^type={relation_type}"

    query_params: Dict[str, Any] = {
        "sysparm_query": query,
        "sysparm_limit": limit,
        "sysparm_offset": offset,
    }

    response = make_sn_request("GET", url, config.timeout, params=query_params)
    data = parse_json_response(response, url)
    result = result_rows(data)
    return {"count": len(result), "relationships": result}
