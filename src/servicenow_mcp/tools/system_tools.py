"""ServiceNow system tools.

Provides system information and property queries.
"""

import logging
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.http import api_request, parse_json_response

logger = logging.getLogger(__name__)


# --- Parameter Models ---


class GetSystemPropertiesParams(BaseModel):
    """Parameters for querying system properties."""

    query: Optional[str] = Field(
        None, description="Filter query (e.g., 'name=glide.servlet.uri' or 'nameLIKEglide')"
    )
    limit: int = Field(20, description="Maximum number of properties to return", ge=1, le=100)


class GetCurrentUserParams(BaseModel):
    """Parameters for getting the current authenticated user info."""

    fields: Optional[str] = Field(
        None, description="Comma-separated fields to return (default: user_name,name,email,roles)"
    )


class GetTableSchemaParams(BaseModel):
    """Parameters for getting a table's schema/dictionary."""

    table_name: str = Field(..., description="The table name to get schema for")
    limit: int = Field(50, description="Maximum number of fields to return", ge=1, le=500)


# --- Tool Implementations ---


def get_system_properties(
    config: ServerConfig, auth_manager: AuthManager, params: GetSystemPropertiesParams
) -> Dict[str, Any]:
    """Query ServiceNow system properties."""
    url = f"{config.api_url}/table/sys_properties"
    query_params: Dict[str, Any] = {
        "sysparm_limit": params.limit,
        "sysparm_fields": "name,value,description",
    }
    if params.query:
        query_params["sysparm_query"] = params.query

    response = api_request("GET", url, auth_manager, config.timeout, params=query_params)
    data = parse_json_response(response, url)
    result = data.get("result", [])
    return {"count": len(result), "properties": result}


def get_current_user(
    config: ServerConfig, auth_manager: AuthManager, params: GetCurrentUserParams
) -> Dict[str, Any]:
    """Get the currently authenticated user's information."""
    url = f"{config.instance_url}/api/now/ui/user/current_user"
    response = api_request("GET", url, auth_manager, config.timeout)
    data = parse_json_response(response, url)
    return data.get("result", {})


def get_table_schema(
    config: ServerConfig, auth_manager: AuthManager, params: GetTableSchemaParams
) -> Dict[str, Any]:
    """Get the data dictionary (schema) for a ServiceNow table."""
    url = f"{config.api_url}/table/sys_dictionary"
    query_params = {
        "sysparm_query": f"name={params.table_name}^internal_type!=collection",
        "sysparm_fields": "element,column_label,internal_type,max_length,mandatory,reference",
        "sysparm_limit": params.limit,
    }

    response = api_request("GET", url, auth_manager, config.timeout, params=query_params)
    data = parse_json_response(response, url)
    result = data.get("result", [])
    fields = [
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
    return {"table": params.table_name, "field_count": len(fields), "fields": fields}
