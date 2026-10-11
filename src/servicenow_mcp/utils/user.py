"""The authenticated caller's identity.

Shared by the ``get_current_user`` tool, the ``servicenow://instance`` resource
and ``set_current_update_set`` (which must write the caller's own preference).
One Table API query on ``sys_user``, so every auth type (basic, OAuth, API key)
gets the same shape. The queries are server-authored, so they are not subject
to the caller-query ``javascript:`` policy.

Roles come from ``sys_user_has_role``, not ``sys_user.roles``: that column is
empty for most users, so it read as ``null`` for every caller. Every lookup is
filtered to the caller; this module never asks about other users' roles (a
``role.name=admin`` filter alone would list every admin on the instance).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from servicenow_mcp.utils.http import build_url, parse_json_response

# Wire name -> sys_user column, for the keys every caller gets.
STANDARD_KEYS = {
    "user_name": "user_name",
    "user_display_name": "name",
    "user_email": "email",
    "user_sys_id": "sys_id",
}

CALLER_ROLE_QUERY = "user=javascript:gs.getUserID()^state=active"
# Direct grants only: inherited rows add dozens of contained roles (47 for a
# plain itil + snc_read_only user) that say nothing the direct ones don't.
DIRECT_ROLES_QUERY = f"{CALLER_ROLE_QUERY}^inherited=false"
ROLE_NAME_RE = re.compile(r"^[A-Za-z0-9_.]+$")
MAX_DIRECT_ROLES = 200


def fetch_current_user(
    api_url: str,
    timeout: int,
    fields: Optional[str] = None,
    *,
    with_roles: bool = True,
) -> Dict[str, Any]:
    """Return the caller's ``sys_user`` row, or ``{}`` if it cannot be read.

    The standard keys (``user_name``, ``user_display_name``, ``user_email``,
    ``user_sys_id``) are always present, plus ``roles`` (the caller's direct,
    active roles; ``None`` if they cannot be read) unless ``with_roles`` is
    false. Any extra ``fields`` are returned under their own column names.
    """
    from servicenow_mcp.server import make_sn_request

    extra = [f.strip() for f in (fields or "").split(",") if f.strip()]
    columns = list(dict.fromkeys([*STANDARD_KEYS.values(), *extra]))
    url = build_url(api_url, "table", "sys_user")
    params: Dict[str, Any] = {
        "sysparm_query": "user_name=javascript:gs.getUserName()",
        "sysparm_limit": 1,
        "sysparm_fields": ",".join(columns),
    }
    response = make_sn_request("GET", url, timeout, params=params)
    rows = parse_json_response(response, url).get("result", [])
    if not rows:
        return {}
    row = rows[0]
    user = {key: row.get(column) for key, column in STANDARD_KEYS.items()}
    if with_roles:
        user["roles"] = fetch_direct_roles(api_url, timeout)
    for column in extra:
        if column not in STANDARD_KEYS.values():
            user[column] = row.get(column)
    return user


def fetch_direct_roles(api_url: str, timeout: int) -> Optional[List[str]]:
    """Return the caller's directly assigned, active role names, or ``None``.

    Rows whose role the caller cannot read come back with a blank name and
    are skipped. ``None`` means the lookup itself failed (no access to
    ``sys_user_has_role``, a sleeping instance).
    """
    from servicenow_mcp.server import make_sn_request

    url = build_url(api_url, "table", "sys_user_has_role")
    params: Dict[str, Any] = {
        "sysparm_query": DIRECT_ROLES_QUERY,
        "sysparm_fields": "role.name",
        "sysparm_limit": MAX_DIRECT_ROLES,
    }
    try:
        response = make_sn_request("GET", url, timeout, params=params)
        rows = parse_json_response(response, url).get("result", [])
    except Exception:
        return None
    names = {row.get("role.name") for row in rows if isinstance(row, dict)}
    return sorted(name for name in names if isinstance(name, str) and name)


def caller_role_query(role: str) -> Optional[str]:
    """The encoded query for the caller's active grant of ``role``.

    ``None`` when ``role`` is not a plain role name, so it can never extend
    the query.
    """
    if not ROLE_NAME_RE.match(role):
        return None
    return f"{CALLER_ROLE_QUERY}^role.name={role}"


def has_role(api_url: str, timeout: int, role: str) -> Optional[bool]:
    """Whether the caller holds ``role`` (directly or inherited), or ``None``.

    One existence query (``limit=1``, ``fields=sys_id``) on the caller's own
    ``sys_user_has_role`` rows. ``None`` on any failure, so callers can tell
    "no" from "could not tell".
    """
    from servicenow_mcp.server import make_sn_request

    query = caller_role_query(role)
    if query is None:
        return None
    url = build_url(api_url, "table", "sys_user_has_role")
    params: Dict[str, Any] = {
        "sysparm_query": query,
        "sysparm_fields": "sys_id",
        "sysparm_limit": 1,
    }
    try:
        response = make_sn_request("GET", url, timeout, params=params)
        rows = parse_json_response(response, url).get("result")
    except Exception:
        return None
    if not isinstance(rows, list):
        return None
    return bool(rows)
