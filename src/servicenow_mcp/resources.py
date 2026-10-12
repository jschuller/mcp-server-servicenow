"""MCP resources — read-only context that clients fetch without a tool call.

Five hand-written resources:
- servicenow://schema/{table_name} — field names, types, references (template)
- servicenow://instance — instance URL, version, logged-in user, timezone
- servicenow://update-set/current — the caller's current update set
- servicenow://cmdb/classes — CMDB class hierarchy from sys_db_object
- servicenow://help/query-syntax — encoded query operators; an alias for
  skill://exploring-tables/references/query-syntax.md

Plus the five Agent Skills under src/servicenow_mcp/skills/, served by FastMCP's
SkillsDirectoryProvider as skill://<name>/SKILL.md, skill://<name>/_manifest
(SHA-256 per file) and skill://<name>/references/<file> — the SEP-2640 convention.
"""

import json
import logging
from importlib.resources import files
from pathlib import Path
from typing import Any, Dict

from fastmcp.server.providers.skills import SkillsDirectoryProvider

from servicenow_mcp.server import mcp, get_config, make_sn_request
from servicenow_mcp.utils.http import build_url, parse_json_response
from servicenow_mcp.utils.schema import _reference_value, fetch_table_schema
from servicenow_mcp.utils.user import fetch_current_user
from servicenow_mcp.tools.update_set_tools import CURRENT_UPDATE_SET_PREF_QUERY

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# servicenow://schema/{table_name}
# ---------------------------------------------------------------------------


@mcp.resource(
    "servicenow://schema/{table_name}",
    description="Field definitions (name, type, label, mandatory, reference, defined_in) for a ServiceNow table including inherited fields. Avoids repeated get_table_schema tool calls.",
    mime_type="application/json",
    tags={"read", "table"},
)
def table_schema(table_name: str) -> str:
    """Return the data dictionary for a ServiceNow table, parents included."""
    config = get_config()
    return json.dumps(
        fetch_table_schema(
            table_name,
            limit=1000,
            timeout=config.timeout,
            api_url=config.api_url,
            include_inherited=True,
        )
    )


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
    props_url = build_url(config.api_url, "table", "sys_properties")
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

    try:
        user = fetch_current_user(config.api_url, config.timeout)
        if user:
            result["user"] = {
                "user_name": user["user_name"],
                "name": user["user_display_name"],
                "email": user["user_email"],
                "roles": user["roles"],
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

    # The caller's own preference row: a row with an empty user is the
    # system-wide default, and another user's row is not ours to report.
    pref_url = build_url(config.api_url, "table", "sys_user_preference")
    pref_params = {
        "sysparm_query": CURRENT_UPDATE_SET_PREF_QUERY,
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
    us_url = build_url(config.api_url, "table", "sys_update_set", update_set_sys_id)
    us_params = {
        "sysparm_fields": "sys_id,name,state,description,application",
    }
    us_resp = make_sn_request("GET", us_url, config.timeout, params=us_params)
    us_data = parse_json_response(us_resp, us_url)
    update_set = us_data.get("result", {})

    return json.dumps(
        {
            "sys_id": update_set.get("sys_id"),
            "name": update_set.get("name"),
            "state": update_set.get("state"),
            "description": update_set.get("description"),
            "application": update_set.get("application"),
        }
    )


# ---------------------------------------------------------------------------
# servicenow://cmdb/classes
# ---------------------------------------------------------------------------


# A base instance has 500+ cmdb_ci* classes; page through them, but stop at a
# bound and say so rather than returning a silently partial list.
CLASS_PAGE_SIZE = 500
MAX_CLASS_PAGES = 10


@mcp.resource(
    "servicenow://cmdb/classes",
    description="CMDB CI class hierarchy — class names, labels, and parent classes",
    mime_type="application/json",
    tags={"read", "cmdb"},
)
def cmdb_classes() -> str:
    """Return the CMDB CI class hierarchy from sys_db_object."""
    config = get_config()

    url = build_url(config.api_url, "table", "sys_db_object")
    result: list[Dict[str, Any]] = []
    truncated = False
    for page in range(MAX_CLASS_PAGES):
        query_params = {
            "sysparm_query": "nameSTARTSWITHcmdb_ci^ORDERBYname",
            # Dot-walk the parent's name so super_class is a usable string
            # rather than a {link, value} reference.
            "sysparm_fields": "name,label,super_class.name,super_class",
            "sysparm_limit": CLASS_PAGE_SIZE,
            "sysparm_offset": page * CLASS_PAGE_SIZE,
        }
        response = make_sn_request("GET", url, config.timeout, params=query_params)
        batch = parse_json_response(response, url).get("result", [])
        result.extend(batch)
        if len(batch) < CLASS_PAGE_SIZE:
            break
    else:
        truncated = True
    classes = [
        {
            "name": r.get("name"),
            "label": r.get("label"),
            "super_class": r.get("super_class.name")
            or _reference_value(r.get("super_class")),
        }
        for r in result
    ]
    body: Dict[str, Any] = {"count": len(classes), "classes": classes}
    if truncated:
        body["truncated"] = True
    return json.dumps(body)


# ---------------------------------------------------------------------------
# servicenow://help/query-syntax
# ---------------------------------------------------------------------------

# The operator reference lives with the exploring-tables skill, so clients that
# load skills natively get it too; this URI stays as an alias for the same file.
_QUERY_SYNTAX_PATH = ("skills", "exploring-tables", "references", "query-syntax.md")


@mcp.resource(
    "servicenow://help/query-syntax",
    description="ServiceNow encoded query operators reference — prevents hallucinated query syntax",
    mime_type="text/markdown",
    tags={"read"},
)
def query_syntax_help() -> str:
    """Return the encoded query syntax reference."""
    return files("servicenow_mcp").joinpath(*_QUERY_SYNTAX_PATH).read_text("utf-8")


# ---------------------------------------------------------------------------
# skill://<name>/... — Agent Skills served over MCP (SEP-2640 convention)
# ---------------------------------------------------------------------------

# The SKILL.md directories ship as package data. FastMCP's provider exposes
# each as skill://<name>/SKILL.md plus a skill://<name>/_manifest (SHA-256 per
# file) and, with supporting_files="resources", every reference file by URI.
_SKILLS_ROOT = Path(str(files("servicenow_mcp").joinpath("skills")))
mcp.add_provider(
    SkillsDirectoryProvider(roots=_SKILLS_ROOT, supporting_files="resources")
)
