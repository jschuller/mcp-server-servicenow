"""Generic ServiceNow Table API tools.

Provides CRUD operations on any ServiceNow table via /api/now/table/{table_name}.
"""

import logging
from typing import Annotated, Any, Dict, Optional

from pydantic import Field

from servicenow_mcp.server import mcp, get_config, make_sn_request
from servicenow_mcp.utils.http import parse_json_response

logger = logging.getLogger(__name__)


@mcp.tool(tags={"read", "table"})
def list_records(
    table_name: Annotated[str, Field(description="The ServiceNow table name (e.g., 'incident', 'sys_user', 'cmdb_ci')")],
    query: Annotated[Optional[str], Field(description="Encoded query string (e.g., 'active=true^priority=1')")] = None,
    fields: Annotated[Optional[str], Field(description="Comma-separated list of fields to return")] = None,
    limit: Annotated[int, Field(ge=1, le=1000, description="Maximum number of records to return")] = 20,
    offset: Annotated[int, Field(ge=0, description="Number of records to skip")] = 0,
    order_by: Annotated[Optional[str], Field(description="Field to order results by (prefix with '-' for descending)")] = None,
) -> Dict[str, Any]:
    """List records from any ServiceNow table with optional filtering, field selection, and pagination"""
    config = get_config()

    url = f"{config.api_url}/table/{table_name}"
    query_params: Dict[str, Any] = {
        "sysparm_limit": limit,
        "sysparm_offset": offset,
    }
    if query:
        query_params["sysparm_query"] = query
    if fields:
        query_params["sysparm_fields"] = fields
    if order_by:
        query_params["sysparm_query"] = (
            f"{query_params.get('sysparm_query', '')}^ORDERBY{order_by}"
        ).lstrip("^")

    response = make_sn_request("GET", url, config.timeout, params=query_params)
    data = parse_json_response(response, url)
    result = data.get("result", [])
    return {"count": len(result), "records": result}


@mcp.tool(tags={"read", "table"})
def get_record(
    table_name: Annotated[str, Field(description="The ServiceNow table name")],
    sys_id: Annotated[str, Field(description="The sys_id of the record")],
    fields: Annotated[Optional[str], Field(description="Comma-separated list of fields to return")] = None,
) -> Dict[str, Any]:
    """Get a single record from a ServiceNow table by sys_id"""
    config = get_config()

    url = f"{config.api_url}/table/{table_name}/{sys_id}"
    query_params: Dict[str, str] = {}
    if fields:
        query_params["sysparm_fields"] = fields

    response = make_sn_request("GET", url, config.timeout, params=query_params)
    data = parse_json_response(response, url)
    return data.get("result", {})


@mcp.tool(tags={"write", "table"})
def create_record(
    table_name: Annotated[str, Field(description="The ServiceNow table name")],
    data: Annotated[Dict[str, Any], Field(description="Record field values as key-value pairs")],
) -> Dict[str, Any]:
    """Create a new record in any ServiceNow table"""
    config = get_config()

    url = f"{config.api_url}/table/{table_name}"
    response = make_sn_request("POST", url, config.timeout, json_data=data)
    resp_data = parse_json_response(response, url)
    result = resp_data.get("result", {})
    return {"sys_id": result.get("sys_id"), "record": result}


@mcp.tool(tags={"write", "table"})
def update_record(
    table_name: Annotated[str, Field(description="The ServiceNow table name")],
    sys_id: Annotated[str, Field(description="The sys_id of the record to update")],
    data: Annotated[Dict[str, Any], Field(description="Fields to update as key-value pairs")],
) -> Dict[str, Any]:
    """Update an existing record in a ServiceNow table"""
    config = get_config()

    url = f"{config.api_url}/table/{table_name}/{sys_id}"
    response = make_sn_request("PATCH", url, config.timeout, json_data=data)
    resp_data = parse_json_response(response, url)
    result = resp_data.get("result", {})
    return {"sys_id": result.get("sys_id"), "record": result}


@mcp.tool(tags={"write", "table"})
def delete_record(
    table_name: Annotated[str, Field(description="The ServiceNow table name")],
    sys_id: Annotated[str, Field(description="The sys_id of the record to delete")],
) -> str:
    """Delete a record from a ServiceNow table by sys_id"""
    config = get_config()

    url = f"{config.api_url}/table/{table_name}/{sys_id}"
    make_sn_request("DELETE", url, config.timeout)
    return f"Record {sys_id} deleted from {table_name}"


@mcp.tool(tags={"read", "table"})
def aggregate_records(
    table_name: Annotated[str, Field(description="The ServiceNow table name (e.g., 'incident', 'cmdb_ci')")],
    count: Annotated[bool, Field(description="Include record count in results")] = True,
    avg_fields: Annotated[Optional[str], Field(description="Comma-separated fields to average (e.g., 'reassignment_count,reopen_count')")] = None,
    min_fields: Annotated[Optional[str], Field(description="Comma-separated fields to find minimum values")] = None,
    max_fields: Annotated[Optional[str], Field(description="Comma-separated fields to find maximum values")] = None,
    sum_fields: Annotated[Optional[str], Field(description="Comma-separated fields to sum")] = None,
    group_by: Annotated[Optional[str], Field(description="Comma-separated fields to group results by (e.g., 'priority,state')")] = None,
    query: Annotated[Optional[str], Field(description="Encoded query string to filter records before aggregation")] = None,
    having: Annotated[Optional[str], Field(description="Post-aggregation filter (e.g., 'COUNT>5')")] = None,
) -> Dict[str, Any]:
    """Aggregate records using COUNT, AVG, MIN, MAX, SUM with optional GROUP BY via the Stats API"""
    config = get_config()

    url = f"{config.api_url}/stats/{table_name}"
    query_params: Dict[str, Any] = {}

    if count:
        query_params["sysparm_count"] = "true"
    if avg_fields:
        query_params["sysparm_avg_fields"] = avg_fields
    if min_fields:
        query_params["sysparm_min_fields"] = min_fields
    if max_fields:
        query_params["sysparm_max_fields"] = max_fields
    if sum_fields:
        query_params["sysparm_sum_fields"] = sum_fields
    if group_by:
        query_params["sysparm_group_by"] = group_by
    if query:
        query_params["sysparm_query"] = query
    if having:
        query_params["sysparm_having"] = having

    response = make_sn_request("GET", url, config.timeout, params=query_params)
    data = parse_json_response(response, url)
    result = data.get("result", {})
    # Stats API returns a list when group_by is used, but a dict otherwise.
    # FastMCP requires tool return values to be dicts.
    if isinstance(result, list):
        return {"count": len(result), "groups": result}
    return result
