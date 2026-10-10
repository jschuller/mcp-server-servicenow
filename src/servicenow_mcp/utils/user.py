"""The authenticated caller's identity.

Shared by the ``get_current_user`` tool, the ``servicenow://instance`` resource
and ``set_current_update_set`` (which must write the caller's own preference).
One Table API query on ``sys_user``, so every auth type (basic, OAuth, API key)
gets the same shape. The query is server-authored, so it is not subject to the
caller-query ``javascript:`` policy.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from servicenow_mcp.utils.http import build_url, parse_json_response

# Wire name -> sys_user column, for the keys every caller gets.
STANDARD_KEYS = {
    "user_name": "user_name",
    "user_display_name": "name",
    "user_email": "email",
    "user_sys_id": "sys_id",
    "roles": "roles",
}


def fetch_current_user(
    api_url: str, timeout: int, fields: Optional[str] = None
) -> Dict[str, Any]:
    """Return the caller's ``sys_user`` row, or ``{}`` if it cannot be read.

    The standard keys (``user_name``, ``user_display_name``, ``user_email``,
    ``user_sys_id``, ``roles``) are always present; any extra ``fields`` are
    returned under their own column names.
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
    for column in extra:
        if column not in STANDARD_KEYS.values():
            user[column] = row.get(column)
    return user
