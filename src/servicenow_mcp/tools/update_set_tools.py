"""ServiceNow Update Set tools.

Provides management of update sets for tracking customizations.
"""

import logging
from typing import Annotated, Any, Dict, Optional

from pydantic import Field

from servicenow_mcp.server import mcp, get_config, make_sn_request
from servicenow_mcp.utils.http import parse_json_response

logger = logging.getLogger(__name__)


@mcp.tool(tags={"read", "updateset"})
def list_update_sets(
    query: Annotated[
        Optional[str],
        Field(
            description="Filter query (e.g., 'state=in progress', 'nameLIKErelease')"
        ),
    ] = None,
    state: Annotated[
        Optional[str],
        Field(
            description="Filter by state: 'in progress', 'complete', 'ignore', or 'default'"
        ),
    ] = None,
    limit: Annotated[
        int, Field(ge=1, le=100, description="Maximum number of update sets to return")
    ] = 20,
) -> Dict[str, Any]:
    """List update sets with optional state and query filtering"""
    config = get_config()

    url = f"{config.api_url}/table/sys_update_set"
    query_parts = []
    if query:
        query_parts.append(query)
    if state:
        query_parts.append(f"state={state}")

    query_params: Dict[str, Any] = {
        "sysparm_limit": limit,
        "sysparm_fields": "sys_id,name,description,state,application,sys_created_on,sys_updated_on",
        "sysparm_query": "^".join(query_parts)
        if query_parts
        else "ORDERBYDESCsys_updated_on",
    }

    response = make_sn_request("GET", url, config.timeout, params=query_params)
    data = parse_json_response(response, url)
    result = data.get("result", [])
    return {"count": len(result), "update_sets": result}


@mcp.tool(tags={"read", "updateset"})
def get_update_set(
    sys_id: Annotated[str, Field(description="The sys_id of the update set")],
) -> Dict[str, Any]:
    """Get details of a specific update set by sys_id"""
    config = get_config()

    url = f"{config.api_url}/table/sys_update_set/{sys_id}"
    response = make_sn_request("GET", url, config.timeout)
    data = parse_json_response(response, url)
    return data.get("result", {})


@mcp.tool(tags={"write", "updateset"})
def create_update_set(
    name: Annotated[str, Field(description="Name of the update set")],
    description: Annotated[
        Optional[str], Field(description="Description of the update set")
    ] = None,
    parent: Annotated[
        Optional[str], Field(description="Parent update set sys_id (for batch sets)")
    ] = None,
) -> Dict[str, Any]:
    """Create a new update set for tracking customizations"""
    config = get_config()

    url = f"{config.api_url}/table/sys_update_set"
    payload: Dict[str, Any] = {"name": name}
    if description:
        payload["description"] = description
    if parent:
        payload["parent"] = parent

    response = make_sn_request("POST", url, config.timeout, json_data=payload)
    data = parse_json_response(response, url)
    result = data.get("result", {})
    return {
        "sys_id": result.get("sys_id"),
        "name": result.get("name"),
        "record": result,
    }


@mcp.tool(tags={"write", "updateset"})
def set_current_update_set(
    sys_id: Annotated[
        str, Field(description="The sys_id of the update set to make current")
    ],
) -> str:
    """Set an update set as the current active update set"""
    config = get_config()

    url = f"{config.api_url}/table/sys_update_set/{sys_id}"
    response = make_sn_request("GET", url, config.timeout)
    data = parse_json_response(response, url)
    update_set = data.get("result", {})

    name = update_set.get("name", "Unknown")
    state = update_set.get("state", "Unknown")

    if state != "in progress":
        return f"Cannot set update set '{name}' as current - state is '{state}' (must be 'in progress')"

    pref_url = f"{config.api_url}/table/sys_user_preference"
    pref_response = make_sn_request(
        "GET",
        pref_url,
        config.timeout,
        params={"sysparm_query": "name=sys_update_set", "sysparm_limit": 1},
    )
    pref_data = parse_json_response(pref_response, pref_url)
    prefs = pref_data.get("result", [])

    if prefs:
        pref_sys_id = prefs[0]["sys_id"]
        make_sn_request(
            "PATCH",
            f"{pref_url}/{pref_sys_id}",
            config.timeout,
            json_data={"value": sys_id},
        )
    else:
        make_sn_request(
            "POST",
            pref_url,
            config.timeout,
            json_data={"name": "sys_update_set", "value": sys_id},
        )

    return f"Current update set changed to '{name}' ({sys_id})"


@mcp.tool(tags={"read", "updateset"})
def list_update_set_changes(
    update_set_sys_id: Annotated[
        str, Field(description="The sys_id of the update set")
    ],
    limit: Annotated[
        int, Field(ge=1, le=500, description="Maximum number of changes to return")
    ] = 50,
) -> Dict[str, Any]:
    """List all customer updates (changes) within an update set"""
    config = get_config()

    url = f"{config.api_url}/table/sys_update_xml"
    query_params = {
        "sysparm_query": f"update_set={update_set_sys_id}^ORDERBYDESCsys_updated_on",
        "sysparm_fields": "sys_id,name,type,target_name,action,sys_created_on",
        "sysparm_limit": limit,
    }

    response = make_sn_request("GET", url, config.timeout, params=query_params)
    data = parse_json_response(response, url)
    result = data.get("result", [])
    return {"count": len(result), "changes": result}
