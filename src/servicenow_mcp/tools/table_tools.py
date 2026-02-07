"""Generic ServiceNow Table API tools.

Provides CRUD operations on any ServiceNow table via /api/now/table/{table_name}.
"""

import logging
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.http import api_request, parse_json_response

logger = logging.getLogger(__name__)


# --- Parameter Models ---


class ListRecordsParams(BaseModel):
    """Parameters for listing records from a ServiceNow table."""

    table_name: str = Field(..., description="The ServiceNow table name (e.g., 'incident', 'sys_user', 'cmdb_ci')")
    query: Optional[str] = Field(None, description="Encoded query string (e.g., 'active=true^priority=1')")
    fields: Optional[str] = Field(None, description="Comma-separated list of fields to return")
    limit: int = Field(20, description="Maximum number of records to return", ge=1, le=1000)
    offset: int = Field(0, description="Number of records to skip", ge=0)
    order_by: Optional[str] = Field(None, description="Field to order results by (prefix with '-' for descending)")


class GetRecordParams(BaseModel):
    """Parameters for getting a single record."""

    table_name: str = Field(..., description="The ServiceNow table name")
    sys_id: str = Field(..., description="The sys_id of the record")
    fields: Optional[str] = Field(None, description="Comma-separated list of fields to return")


class CreateRecordParams(BaseModel):
    """Parameters for creating a new record."""

    table_name: str = Field(..., description="The ServiceNow table name")
    data: Dict[str, Any] = Field(..., description="Record field values as key-value pairs")


class UpdateRecordParams(BaseModel):
    """Parameters for updating an existing record."""

    table_name: str = Field(..., description="The ServiceNow table name")
    sys_id: str = Field(..., description="The sys_id of the record to update")
    data: Dict[str, Any] = Field(..., description="Fields to update as key-value pairs")


class DeleteRecordParams(BaseModel):
    """Parameters for deleting a record."""

    table_name: str = Field(..., description="The ServiceNow table name")
    sys_id: str = Field(..., description="The sys_id of the record to delete")


# --- Tool Implementations ---


def list_records(
    config: ServerConfig, auth_manager: AuthManager, params: ListRecordsParams
) -> Dict[str, Any]:
    """List records from a ServiceNow table."""
    url = f"{config.api_url}/table/{params.table_name}"
    query_params: Dict[str, Any] = {
        "sysparm_limit": params.limit,
        "sysparm_offset": params.offset,
    }
    if params.query:
        query_params["sysparm_query"] = params.query
    if params.fields:
        query_params["sysparm_fields"] = params.fields
    if params.order_by:
        query_params["sysparm_query"] = (
            f"{query_params.get('sysparm_query', '')}^ORDERBY{params.order_by}"
        ).lstrip("^")

    response = api_request("GET", url, auth_manager, config.timeout, params=query_params)
    data = parse_json_response(response, url)
    result = data.get("result", [])
    return {"count": len(result), "records": result}


def get_record(
    config: ServerConfig, auth_manager: AuthManager, params: GetRecordParams
) -> Dict[str, Any]:
    """Get a single record by sys_id."""
    url = f"{config.api_url}/table/{params.table_name}/{params.sys_id}"
    query_params: Dict[str, str] = {}
    if params.fields:
        query_params["sysparm_fields"] = params.fields

    response = api_request("GET", url, auth_manager, config.timeout, params=query_params)
    data = parse_json_response(response, url)
    return data.get("result", {})


def create_record(
    config: ServerConfig, auth_manager: AuthManager, params: CreateRecordParams
) -> Dict[str, Any]:
    """Create a new record in a ServiceNow table."""
    url = f"{config.api_url}/table/{params.table_name}"
    response = api_request("POST", url, auth_manager, config.timeout, json_data=params.data)
    data = parse_json_response(response, url)
    result = data.get("result", {})
    return {"sys_id": result.get("sys_id"), "record": result}


def update_record(
    config: ServerConfig, auth_manager: AuthManager, params: UpdateRecordParams
) -> Dict[str, Any]:
    """Update an existing record in a ServiceNow table."""
    url = f"{config.api_url}/table/{params.table_name}/{params.sys_id}"
    response = api_request("PATCH", url, auth_manager, config.timeout, json_data=params.data)
    data = parse_json_response(response, url)
    result = data.get("result", {})
    return {"sys_id": result.get("sys_id"), "record": result}


def delete_record(
    config: ServerConfig, auth_manager: AuthManager, params: DeleteRecordParams
) -> str:
    """Delete a record from a ServiceNow table."""
    url = f"{config.api_url}/table/{params.table_name}/{params.sys_id}"
    api_request("DELETE", url, auth_manager, config.timeout)
    return f"Record {params.sys_id} deleted from {params.table_name}"
