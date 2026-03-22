"""MCP Resources — read-only context for LLM clients.

Provides 5 resources:
- servicenow://schema/{table_name} — field definitions for any table
- servicenow://instance — instance URL, version, user, timezone
- servicenow://update-set/current — currently active update set
- servicenow://cmdb/classes — CMDB CI class hierarchy
- servicenow://help/query-syntax — encoded query operators reference
"""

import json
import logging
from typing import Any, Dict

from servicenow_mcp.server import mcp, get_config, make_sn_request
from servicenow_mcp.utils.http import parse_json_response

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# servicenow://schema/{table_name}
# ---------------------------------------------------------------------------

@mcp.resource(
    "servicenow://schema/{table_name}",
    description="Field definitions (name, type, label, mandatory, reference) for a ServiceNow table. Avoids repeated get_table_schema tool calls.",
    mime_type="application/json",
    tags={"read", "table"},
)
def table_schema(table_name: str) -> str:
    """Return the data dictionary for a ServiceNow table."""
    config = get_config()

    url = f"{config.api_url}/table/sys_dictionary"
    query_params = {
        "sysparm_query": f"name={table_name}^internal_type!=collection",
        "sysparm_fields": "element,column_label,internal_type,max_length,mandatory,reference",
        "sysparm_limit": 500,
    }

    response = make_sn_request("GET", url, config.timeout, params=query_params)
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
    return json.dumps({"table": table_name, "field_count": len(fields_list), "fields": fields_list})


# ---------------------------------------------------------------------------
# servicenow://instance
# ---------------------------------------------------------------------------

@mcp.resource(
    "servicenow://instance",
    description="Instance URL, platform version, logged-in user, and timezone",
    mime_type="application/json",
    tags={"read", "admin"},
)
def instance_info() -> str:
    """Return instance metadata: URL, version, timezone, and current user."""
    config = get_config()
    result: Dict[str, Any] = {"instance_url": config.instance_url}

    # Fetch version + timezone in one call
    props_url = f"{config.api_url}/table/sys_properties"
    props_params = {
        "sysparm_query": "nameINglide.product.version,glide.sys.timezone",
        "sysparm_fields": "name,value",
        "sysparm_limit": 10,
    }
    try:
        resp = make_sn_request("GET", props_url, config.timeout, params=props_params)
        props_data = parse_json_response(resp, props_url)
        for prop in props_data.get("result", []):
            name = prop.get("name", "")
            if name == "glide.product.version":
                result["version"] = prop.get("value")
            elif name == "glide.sys.timezone":
                result["timezone"] = prop.get("value")
    except Exception:
        logger.debug("Failed to fetch system properties for instance resource")

    # Fetch current user
    try:
        user_url = f"{config.instance_url}/api/now/ui/user/current_user"
        user_resp = make_sn_request("GET", user_url, config.timeout)
        user_data = parse_json_response(user_resp, user_url)
        user = user_data.get("result", {})
        result["user"] = {
            "user_name": user.get("user_name"),
            "name": user.get("name"),
            "email": user.get("email"),
        }
    except Exception:
        # Fallback: Table API
        try:
            table_url = f"{config.api_url}/table/sys_user"
            user_params = {
                "sysparm_query": "user_name=javascript:gs.getUserName()",
                "sysparm_limit": 1,
                "sysparm_fields": "user_name,name,email",
            }
            user_resp = make_sn_request("GET", table_url, config.timeout, params=user_params)
            user_data = parse_json_response(user_resp, table_url)
            users = user_data.get("result", [])
            if users:
                u = users[0]
                result["user"] = {
                    "user_name": u.get("user_name"),
                    "name": u.get("name"),
                    "email": u.get("email"),
                }
        except Exception:
            logger.debug("Failed to fetch current user for instance resource")

    return json.dumps(result)


# ---------------------------------------------------------------------------
# servicenow://update-set/current
# ---------------------------------------------------------------------------

@mcp.resource(
    "servicenow://update-set/current",
    description="Currently active update set name, sys_id, and state",
    mime_type="application/json",
    tags={"read", "updateset"},
)
def current_update_set() -> str:
    """Return the currently active update set."""
    config = get_config()

    # Get current update set sys_id from user preference
    pref_url = f"{config.api_url}/table/sys_user_preference"
    pref_params = {
        "sysparm_query": "name=sys_update_set",
        "sysparm_limit": 1,
        "sysparm_fields": "value",
    }
    resp = make_sn_request("GET", pref_url, config.timeout, params=pref_params)
    pref_data = parse_json_response(resp, pref_url)
    prefs = pref_data.get("result", [])

    if not prefs or not prefs[0].get("value"):
        return json.dumps({"error": "No current update set found in user preferences"})

    update_set_sys_id = prefs[0]["value"]

    # Fetch the update set details
    us_url = f"{config.api_url}/table/sys_update_set/{update_set_sys_id}"
    us_params = {
        "sysparm_fields": "sys_id,name,state,description,application",
    }
    us_resp = make_sn_request("GET", us_url, config.timeout, params=us_params)
    us_data = parse_json_response(us_resp, us_url)
    update_set = us_data.get("result", {})

    return json.dumps({
        "sys_id": update_set.get("sys_id"),
        "name": update_set.get("name"),
        "state": update_set.get("state"),
        "description": update_set.get("description"),
        "application": update_set.get("application"),
    })


# ---------------------------------------------------------------------------
# servicenow://cmdb/classes
# ---------------------------------------------------------------------------

@mcp.resource(
    "servicenow://cmdb/classes",
    description="CMDB CI class hierarchy — class names, labels, and parent classes",
    mime_type="application/json",
    tags={"read", "cmdb"},
)
def cmdb_classes() -> str:
    """Return the CMDB CI class hierarchy from sys_db_object."""
    config = get_config()

    url = f"{config.api_url}/table/sys_db_object"
    query_params = {
        "sysparm_query": "nameSTARTSWITHcmdb_ci^ORDERBYname",
        "sysparm_fields": "name,label,super_class",
        "sysparm_limit": 200,
    }

    response = make_sn_request("GET", url, config.timeout, params=query_params)
    data = parse_json_response(response, url)
    result = data.get("result", [])
    classes = [
        {
            "name": r.get("name"),
            "label": r.get("label"),
            "super_class": r.get("super_class"),
        }
        for r in result
    ]
    return json.dumps({"count": len(classes), "classes": classes})


# ---------------------------------------------------------------------------
# servicenow://help/query-syntax
# ---------------------------------------------------------------------------

_QUERY_SYNTAX_REFERENCE = """\
# ServiceNow Encoded Query Syntax

## Comparison Operators

| Operator | Meaning | Example |
|----------|---------|---------|
| `=` | Equals | `active=true` |
| `!=` | Not equals | `state!=6` |
| `LIKE` | Contains | `short_descriptionLIKEnetwork` |
| `NOT LIKE` | Does not contain | `short_descriptionNOT LIKEtest` |
| `STARTSWITH` | Starts with | `numberSTARTSWITHINC` |
| `ENDSWITH` | Ends with | `nameENDSWITHserver` |
| `IN` | In list (comma-separated) | `stateIN1,2,3` |
| `NOT IN` | Not in list | `stateNOT IN6,7` |
| `ISEMPTY` | Field is empty | `assignmentISEMPTY` |
| `ISNOTEMPTY` | Field is not empty | `assigned_toISNOTEMPTY` |
| `INSTANCEOF` | Is instance of class | `sys_class_nameINSTANCEOFcmdb_ci_server` |

## Numeric / Date Operators

| Operator | Meaning | Example |
|----------|---------|---------|
| `>` | Greater than | `priority>2` |
| `>=` | Greater than or equal | `priority>=2` |
| `<` | Less than | `priority<3` |
| `<=` | Less than or equal | `priority<=3` |
| `BETWEEN` | Between two values | `priorityBETWEEN1@3` |
| `SAMEAS` | Same as field | `opened_bySAMEAScaller_id` |
| `NSAMEAS` | Not same as field | `opened_byNSAMEAScaller_id` |
| `GT_FIELD` | Greater than field | `sys_updated_onGT_FIELDsys_created_on` |
| `LT_FIELD` | Less than field | `sys_updated_onLT_FIELDsys_created_on` |

## Relative Date Operators

| Operator | Meaning | Example |
|----------|---------|---------|
| `RELATIVEGT` | After relative date | `sys_created_onRELATIVEGT@year@ago@1` |
| `RELATIVELT` | Before relative date | `sys_created_onRELATIVELT@dayofweek@ago@3` |
| `MORETHAN` | More than N units ago | `sys_created_onMORETHAN30@dayofweek@ago` |
| `LESSTHAN` | Less than N units ago | `sys_created_onLESSTHAN7@dayofweek@ago` |
| `DATEPART` | Date part equals | `sys_created_onDATEPART2024@year` |
| `javascript:gs.daysAgo(N)` | N days ago | `sys_created_on>=javascript:gs.daysAgo(7)` |
| `javascript:gs.beginningOfLastMonth()` | Start of last month | `sys_created_on>=javascript:gs.beginningOfLastMonth()` |

## Join Operators

| Operator | Meaning | Example |
|----------|---------|---------|
| `^` | AND | `active=true^priority=1` |
| `^OR` | OR | `priority=1^ORpriority=2` |
| `^NQ` | New query (UNION) | `active=true^NQstate=6` |

## Order Operators

| Operator | Meaning | Example |
|----------|---------|---------|
| `ORDERBY` | Sort ascending | `active=true^ORDERBYnumber` |
| `ORDERBYDESC` | Sort descending | `active=true^ORDERBYDESCsys_created_on` |

## Common Patterns

```
# Active P1 incidents assigned to someone, newest first
active=true^priority=1^assigned_toISNOTEMPTY^ORDERBYDESCsys_created_on

# Incidents created in last 7 days
sys_created_on>=javascript:gs.daysAgo(7)

# CIs of type Server or Linux Server
sys_class_nameINSTANCEOFcmdb_ci_server

# Open incidents for a specific CI
active=true^cmdb_ci=<sys_id>

# Records updated today
sys_updated_on>=javascript:gs.beginningOfToday()
```
"""


@mcp.resource(
    "servicenow://help/query-syntax",
    description="ServiceNow encoded query operators reference — prevents hallucinated query syntax",
    mime_type="text/markdown",
    tags={"read"},
)
def query_syntax_help() -> str:
    """Return the encoded query syntax reference."""
    return _QUERY_SYNTAX_REFERENCE
