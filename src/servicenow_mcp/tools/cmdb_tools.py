"""ServiceNow CMDB tools.

Provides operations on CMDB configuration items via the Table API.
"""

import logging
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.http import api_request, parse_json_response

logger = logging.getLogger(__name__)


# --- Parameter Models ---


class ListCIParams(BaseModel):
    """Parameters for listing CMDB configuration items."""

    class_name: str = Field(
        "cmdb_ci", description="CMDB class name (e.g., 'cmdb_ci', 'cmdb_ci_server', 'cmdb_ci_computer')"
    )
    query: Optional[str] = Field(None, description="Encoded query string (e.g., 'operational_status=1')")
    fields: Optional[str] = Field(None, description="Comma-separated list of fields to return")
    limit: int = Field(20, description="Maximum number of CIs to return", ge=1, le=1000)
    offset: int = Field(0, description="Number of records to skip", ge=0)


class GetCIParams(BaseModel):
    """Parameters for getting a single CI."""

    class_name: str = Field("cmdb_ci", description="CMDB class name")
    sys_id: str = Field(..., description="The sys_id of the CI")


class CreateCIParams(BaseModel):
    """Parameters for creating a new CI."""

    class_name: str = Field("cmdb_ci", description="CMDB class name")
    data: Dict[str, Any] = Field(..., description="CI attributes as key-value pairs (must include 'name')")


class UpdateCIParams(BaseModel):
    """Parameters for updating a CI."""

    class_name: str = Field("cmdb_ci", description="CMDB class name")
    sys_id: str = Field(..., description="The sys_id of the CI to update")
    data: Dict[str, Any] = Field(..., description="CI attributes to update")


class GetCIRelationshipsParams(BaseModel):
    """Parameters for getting CI relationships."""

    sys_id: str = Field(..., description="The sys_id of the CI")
    relation_type: Optional[str] = Field(None, description="Filter by relationship type sys_id")


# --- Tool Implementations ---


def list_ci(
    config: ServerConfig, auth_manager: AuthManager, params: ListCIParams
) -> Dict[str, Any]:
    """List CMDB configuration items."""
    url = f"{config.api_url}/table/{params.class_name}"
    query_params: Dict[str, Any] = {
        "sysparm_limit": params.limit,
        "sysparm_offset": params.offset,
    }
    if params.query:
        query_params["sysparm_query"] = params.query
    if params.fields:
        query_params["sysparm_fields"] = params.fields

    response = api_request("GET", url, auth_manager, config.timeout, params=query_params)
    data = parse_json_response(response, url)
    result = data.get("result", [])
    return {"count": len(result), "class": params.class_name, "records": result}


def get_ci(
    config: ServerConfig, auth_manager: AuthManager, params: GetCIParams
) -> Dict[str, Any]:
    """Get a single CMDB configuration item."""
    url = f"{config.api_url}/table/{params.class_name}/{params.sys_id}"
    response = api_request("GET", url, auth_manager, config.timeout)
    data = parse_json_response(response, url)
    return data.get("result", {})


def create_ci(
    config: ServerConfig, auth_manager: AuthManager, params: CreateCIParams
) -> Dict[str, Any]:
    """Create a new CMDB configuration item."""
    url = f"{config.api_url}/table/{params.class_name}"
    response = api_request("POST", url, auth_manager, config.timeout, json_data=params.data)
    data = parse_json_response(response, url)
    result = data.get("result", {})
    return {"sys_id": result.get("sys_id"), "record": result}


def update_ci(
    config: ServerConfig, auth_manager: AuthManager, params: UpdateCIParams
) -> Dict[str, Any]:
    """Update a CMDB configuration item."""
    url = f"{config.api_url}/table/{params.class_name}/{params.sys_id}"
    response = api_request("PATCH", url, auth_manager, config.timeout, json_data=params.data)
    data = parse_json_response(response, url)
    result = data.get("result", {})
    return {"sys_id": result.get("sys_id"), "record": result}


def get_ci_relationships(
    config: ServerConfig, auth_manager: AuthManager, params: GetCIRelationshipsParams
) -> Dict[str, Any]:
    """Get relationships for a CMDB configuration item."""
    url = f"{config.api_url}/table/cmdb_rel_ci"
    query = f"parent={params.sys_id}^ORchild={params.sys_id}"
    if params.relation_type:
        query += f"^type={params.relation_type}"

    query_params = {
        "sysparm_query": query,
        "sysparm_limit": 100,
    }

    response = api_request("GET", url, auth_manager, config.timeout, params=query_params)
    data = parse_json_response(response, url)
    result = data.get("result", [])
    return {"count": len(result), "relationships": result}
