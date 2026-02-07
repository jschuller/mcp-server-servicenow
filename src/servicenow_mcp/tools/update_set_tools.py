"""ServiceNow Update Set tools.

Provides management of update sets for tracking customizations.
"""

import logging
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.http import api_request, parse_json_response

logger = logging.getLogger(__name__)


# --- Parameter Models ---


class ListUpdateSetsParams(BaseModel):
    """Parameters for listing update sets."""

    query: Optional[str] = Field(
        None, description="Filter query (e.g., 'state=in progress', 'nameLIKErelease')"
    )
    state: Optional[str] = Field(
        None, description="Filter by state: 'in progress', 'complete', 'ignore', or 'default'"
    )
    limit: int = Field(20, description="Maximum number of update sets to return", ge=1, le=100)


class GetUpdateSetParams(BaseModel):
    """Parameters for getting a single update set."""

    sys_id: str = Field(..., description="The sys_id of the update set")


class CreateUpdateSetParams(BaseModel):
    """Parameters for creating a new update set."""

    name: str = Field(..., description="Name of the update set")
    description: Optional[str] = Field(None, description="Description of the update set")
    parent: Optional[str] = Field(None, description="Parent update set sys_id (for batch sets)")


class SetCurrentUpdateSetParams(BaseModel):
    """Parameters for setting the current (active) update set."""

    sys_id: str = Field(..., description="The sys_id of the update set to make current")


class ListUpdateSetChangesParams(BaseModel):
    """Parameters for listing changes in an update set."""

    update_set_sys_id: str = Field(..., description="The sys_id of the update set")
    limit: int = Field(50, description="Maximum number of changes to return", ge=1, le=500)


# --- Tool Implementations ---


def list_update_sets(
    config: ServerConfig, auth_manager: AuthManager, params: ListUpdateSetsParams
) -> Dict[str, Any]:
    """List update sets in the ServiceNow instance."""
    url = f"{config.api_url}/table/sys_update_set"
    query_parts = []
    if params.query:
        query_parts.append(params.query)
    if params.state:
        query_parts.append(f"state={params.state}")

    query_params: Dict[str, Any] = {
        "sysparm_limit": params.limit,
        "sysparm_fields": "sys_id,name,description,state,application,sys_created_on,sys_updated_on",
        "sysparm_query": "^".join(query_parts) if query_parts else "ORDERBYDESCsys_updated_on",
    }

    response = api_request("GET", url, auth_manager, config.timeout, params=query_params)
    data = parse_json_response(response, url)
    result = data.get("result", [])
    return {"count": len(result), "update_sets": result}


def get_update_set(
    config: ServerConfig, auth_manager: AuthManager, params: GetUpdateSetParams
) -> Dict[str, Any]:
    """Get details of a specific update set."""
    url = f"{config.api_url}/table/sys_update_set/{params.sys_id}"
    response = api_request("GET", url, auth_manager, config.timeout)
    data = parse_json_response(response, url)
    return data.get("result", {})


def create_update_set(
    config: ServerConfig, auth_manager: AuthManager, params: CreateUpdateSetParams
) -> Dict[str, Any]:
    """Create a new update set."""
    url = f"{config.api_url}/table/sys_update_set"
    payload: Dict[str, Any] = {"name": params.name}
    if params.description:
        payload["description"] = params.description
    if params.parent:
        payload["parent"] = params.parent

    response = api_request("POST", url, auth_manager, config.timeout, json_data=payload)
    data = parse_json_response(response, url)
    result = data.get("result", {})
    return {"sys_id": result.get("sys_id"), "name": result.get("name"), "record": result}


def set_current_update_set(
    config: ServerConfig, auth_manager: AuthManager, params: SetCurrentUpdateSetParams
) -> str:
    """Set an update set as the current (active) update set for the session."""
    url = f"{config.api_url}/table/sys_update_set/{params.sys_id}"
    response = api_request("GET", url, auth_manager, config.timeout)
    data = parse_json_response(response, url)
    update_set = data.get("result", {})

    name = update_set.get("name", "Unknown")
    state = update_set.get("state", "Unknown")

    if state != "in progress":
        return f"Cannot set update set '{name}' as current - state is '{state}' (must be 'in progress')"

    pref_url = f"{config.api_url}/table/sys_user_preference"
    pref_response = api_request(
        "GET", pref_url, auth_manager, config.timeout,
        params={"sysparm_query": "name=sys_update_set", "sysparm_limit": 1},
    )
    pref_data = parse_json_response(pref_response, pref_url)
    prefs = pref_data.get("result", [])

    if prefs:
        pref_sys_id = prefs[0]["sys_id"]
        api_request(
            "PATCH", f"{pref_url}/{pref_sys_id}", auth_manager, config.timeout,
            json_data={"value": params.sys_id},
        )
    else:
        api_request(
            "POST", pref_url, auth_manager, config.timeout,
            json_data={"name": "sys_update_set", "value": params.sys_id},
        )

    return f"Current update set changed to '{name}' ({params.sys_id})"


def list_update_set_changes(
    config: ServerConfig, auth_manager: AuthManager, params: ListUpdateSetChangesParams
) -> Dict[str, Any]:
    """List the customer updates (changes) in an update set."""
    url = f"{config.api_url}/table/sys_update_xml"
    query_params = {
        "sysparm_query": f"update_set={params.update_set_sys_id}^ORDERBYDESCsys_updated_on",
        "sysparm_fields": "sys_id,name,type,target_name,action,sys_created_on",
        "sysparm_limit": params.limit,
    }

    response = api_request("GET", url, auth_manager, config.timeout, params=query_params)
    data = parse_json_response(response, url)
    result = data.get("result", [])
    return {"count": len(result), "changes": result}
