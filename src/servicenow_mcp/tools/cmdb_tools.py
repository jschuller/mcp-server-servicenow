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
    display_note,
    display_value_params,
    drop_added_fields,
    fields_with_query_fields,
    guarded_record,
    list_warning,
    query_field_names,
    response_format_params,
    written_record,
)
from servicenow_mcp.utils.http import build_url, parse_json_response, result_rows
from servicenow_mcp.utils.redaction import Guard, check_property_write

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
    query_names, unknown = query_field_names(query)
    sysparm_fields, added = fields_with_query_fields(fields, query_names)
    # class_name can be any table, so the same guard as list_records.
    guard = Guard(class_name, sysparm_fields, display_value)
    if query:
        query_params["sysparm_query"] = query
    if guard.fields:
        query_params["sysparm_fields"] = guard.fields
    query_params.update(response_format_params(response_format))
    query_params.update(display_value_params(guard.display_value))

    response = make_sn_request("GET", url, config.timeout, params=query_params)
    data = parse_json_response(response, url)
    result = result_rows(data)
    warnings = [
        guard.apply(result, query),
        list_warning(class_name, fields, query_names, unknown, result),
    ]
    warning = " ".join(text for text in warnings if text)
    drop_added_fields(result, added)
    payload: CIList = {"count": len(result), "class": class_name, "records": result}
    if warning:
        payload["warning"] = warning
    note = display_note(display_value, result)
    if note:
        payload["display_note"] = note
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
    guard = Guard(class_name, None, display_value)
    params = display_value_params(guard.display_value)
    response = make_sn_request("GET", url, config.timeout, params=params or None)
    data = parse_json_response(response, url)
    return guarded_record(guard, data)


@mcp.tool(tags={"write", "cmdb"}, annotations=annotations.CREATE)
def create_ci(
    data: Annotated[
        Dict[str, Any],
        Field(description="CI attributes as key-value pairs (must include 'name')"),
    ],
    class_name: Annotated[str, Field(description="CMDB class name")] = "cmdb_ci",
) -> Dict[str, Any]:
    """Create a new CMDB configuration item"""
    check_property_write(class_name, data, update=False)
    config = get_config()

    url = build_url(config.api_url, "table", class_name)
    response = make_sn_request("POST", url, config.timeout, json_data=data)
    return written_record(class_name, parse_json_response(response, url))


@mcp.tool(tags={"write", "cmdb"}, annotations=annotations.UPDATE)
def update_ci(
    sys_id: Annotated[str, Field(description="The sys_id of the CI to update")],
    data: Annotated[Dict[str, Any], Field(description="CI attributes to update")],
    class_name: Annotated[str, Field(description="CMDB class name")] = "cmdb_ci",
) -> Dict[str, Any]:
    """Update a CMDB configuration item"""
    check_property_write(class_name, data, update=True)
    config = get_config()

    url = build_url(config.api_url, "table", class_name, sys_id)
    response = make_sn_request("PATCH", url, config.timeout, json_data=data)
    return written_record(class_name, parse_json_response(response, url))


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
