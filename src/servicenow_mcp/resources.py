"""MCP resources — read-only context that clients fetch without a tool call.

Five hand-written resources:
- servicenow://schema/{table_name} — field names, types, references (template)
- servicenow://instance — instance URL, build, time zones, logged-in user;
  ``unavailable`` says what this identity couldn't read
- servicenow://update-set/current — the caller's current update set
- servicenow://cmdb/classes — CMDB class hierarchy from sys_db_object
- servicenow://help/query-syntax — encoded query operators; an alias for
  skill://exploring-tables/references/query-syntax.md

Plus the four Agent Skills under src/servicenow_mcp/skills/, served by FastMCP's
SkillsDirectoryProvider as skill://<name>/SKILL.md, skill://<name>/_manifest
(SHA-256 per file) and skill://<name>/references/<file> — the SEP-2640 convention.

With SERVICENOW_SKILLS=off (``ServerConfig.skills``) neither the skills nor the
query-syntax alias is registered: the alias is a skill reference file, and "off"
means no packaged skill text reaches the model by any URI. The other four
resources are data, not skills, and are served either way. The switch is read
when this module is first imported, which the CLI does after init_services().
"""

import json
import logging
import re
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any, Dict

from fastmcp import FastMCP
from fastmcp.server.providers.skills import SkillsDirectoryProvider

from servicenow_mcp.server import get_config, get_config_or_none, make_sn_request, mcp
from servicenow_mcp.utils.http import build_url, parse_json_response, result_rows
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


# The build is glide.war (e.g. glide-brazil-08-25-2026__patch0-…zip); the
# default zone is glide.sys.default.tz. glide.product.version and
# glide.sys.timezone are older names, kept as a fallback. Only admin can read
# sys_properties: other identities get 0 rows, not a 403.
INSTANCE_PROPERTIES = (
    "glide.war",
    "glide.sys.default.tz",
    "glide.product.version",
    "glide.sys.timezone",
)
_RELEASE_FAMILY_RE = re.compile(r"glide-([a-z]+)-")
_NO_PROPERTIES = "sys_properties returned no such property: reading it needs admin"


def _reason(exc: Exception) -> str:
    """The first sentence of an error, short enough for a JSON value."""
    return str(exc).split(". ")[0][:120]


@mcp.resource(
    "servicenow://instance",
    description="Instance URL, build and release family, default time zone, and the logged-in user with roles and time zone; unavailable names each value this identity can't read, and why",
    mime_type="application/json",
    tags={"read", "admin"},
)
def instance_info() -> str:
    """Return instance metadata: URL, build, time zones, and current user.

    A value that can't be read is never dropped silently: ``unavailable``
    maps its key to the reason.
    """
    config = get_config()
    result: Dict[str, Any] = {"instance_url": config.instance_url}
    unavailable: Dict[str, str] = {}

    props: Dict[str, str] = {}
    props_error = ""
    props_url = build_url(config.api_url, "table", "sys_properties")
    props_params = {
        "sysparm_query": "nameIN" + ",".join(INSTANCE_PROPERTIES),
        "sysparm_fields": "name,value",
        "sysparm_limit": 10,
    }
    try:
        resp = make_sn_request("GET", props_url, config.timeout, params=props_params)
        for prop in result_rows(parse_json_response(resp, props_url)):
            if isinstance(prop, dict) and isinstance(prop.get("name"), str):
                props[prop["name"]] = str(prop.get("value") or "")
    except Exception as exc:
        logger.debug("Failed to fetch system properties for instance resource")
        props_error = f"sys_properties could not be read: {_reason(exc)}"

    war = props.get("glide.war", "")
    if war:
        result["version"] = war.removesuffix(".zip")
        family = _RELEASE_FAMILY_RE.match(war)
        if family:
            result["release_family"] = family.group(1)
    elif props.get("glide.product.version"):
        result["version"] = props["glide.product.version"]
    elif props:
        # Other properties came back, but a property can have its own read
        # roles, so these may be unset or hidden.
        unavailable["version"] = (
            "glide.war and glide.product.version did not come back: not set, or "
            "not readable with this identity"
        )
    else:
        unavailable["version"] = props_error or _NO_PROPERTIES

    timezone = props.get("glide.sys.default.tz") or props.get("glide.sys.timezone")
    if timezone:
        result["timezone"] = timezone
    elif props:
        unavailable["timezone"] = (
            "glide.sys.default.tz is empty or not readable with this identity; if "
            "empty, the instance's built-in default applies"
        )
    else:
        unavailable["timezone"] = props_error or _NO_PROPERTIES

    try:
        user = fetch_current_user(config.api_url, config.timeout, "time_zone")
        user_error = "the caller's sys_user row could not be read"
    except Exception as exc:
        logger.debug("Failed to fetch current user for instance resource")
        user, user_error = {}, f"sys_user could not be read: {_reason(exc)}"
    if user:
        result["user"] = {
            "user_name": user["user_name"],
            "name": user["user_display_name"],
            "email": user["user_email"],
            "roles": user["roles"],
            "time_zone": user.get("time_zone") or None,
        }
        if user["roles"] is None:
            unavailable["user.roles"] = "the caller's role rows could not be read"
        if user.get("time_zone") is None:
            # A field ACL drops the key; an empty value means none is set.
            unavailable["user.time_zone"] = "sys_user.time_zone is not readable"
        elif not user["time_zone"]:
            unavailable["user.time_zone"] = (
                "the user has no time zone set: display values use the instance default"
            )
    else:
        unavailable["user"] = user_error

    if unavailable:
        result["unavailable"] = unavailable
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


@lru_cache(maxsize=1)
def _query_syntax_text() -> str:
    """The packaged reference, read once: it can't change while the server runs."""
    return files("servicenow_mcp").joinpath(*_QUERY_SYNTAX_PATH).read_text("utf-8")


def query_syntax_help() -> str:
    """Return the encoded query syntax reference."""
    return _query_syntax_text()


# ---------------------------------------------------------------------------
# skill://<name>/... — Agent Skills served over MCP (SEP-2640 convention)
# ---------------------------------------------------------------------------

# The SKILL.md directories ship as package data. FastMCP's provider exposes
# each as skill://<name>/SKILL.md plus a skill://<name>/_manifest (SHA-256 per
# file) and, with supporting_files="resources", every reference file by URI.
_SKILLS_ROOT = Path(str(files("servicenow_mcp").joinpath("skills")))


def register_skills(server: FastMCP) -> None:
    """Serve the packaged skills, and the query-syntax alias, on ``server``."""
    server.resource(
        "servicenow://help/query-syntax",
        description="ServiceNow encoded query operators reference — prevents hallucinated query syntax",
        mime_type="text/markdown",
        tags={"read"},
    )(query_syntax_help)
    server.add_provider(
        SkillsDirectoryProvider(roots=_SKILLS_ROOT, supporting_files="resources")
    )


def _skills_configured() -> bool:
    """On unless the config says off; a library import without a config gets them."""
    config = get_config_or_none()
    return config is None or config.skills


# Whether this process serves the skills; the CLI checks it against its config.
SKILLS_SERVED = _skills_configured()
if SKILLS_SERVED:
    register_skills(mcp)
else:
    logger.info(
        "SERVICENOW_SKILLS=off: skill:// resources and the query-syntax alias not registered"
    )
