"""Table schema (sys_dictionary) fetching with super_class inheritance.

Shared by the ``get_table_schema`` tool and the ``servicenow://schema/{table}``
resource. ServiceNow stores each table's *own* columns under its name in
``sys_dictionary``; inherited columns (``incident`` → ``task``) live under the
parent. Without walking ``sys_db_object.super_class`` an ``incident`` schema
looks like it has no ``number`` or ``short_description``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from servicenow_mcp.utils.http import (
    ServiceNowAPIError,
    build_url,
    parse_json_response,
    result_rows,
)

logger = logging.getLogger(__name__)

MAX_DEPTH = 10
DICTIONARY_FIELDS = (
    "name,element,column_label,internal_type,max_length,mandatory,reference"
)


def _reference_value(value: Any) -> str:
    """Table API reference fields arrive as {"link", "value"} or as a string."""
    if isinstance(value, dict):
        return str(value.get("value") or "")
    if isinstance(value, str):
        return value
    return ""


def table_hierarchy(api_url: str, table_name: str, timeout: int) -> List[str]:
    """Return [table, parent, grandparent, ...] by walking sys_db_object by sys_id.

    Degrades to ``[table_name]`` when ``sys_db_object`` is unreadable (403 for
    non-admin OAuth users) or the table is unknown.
    """
    return _walk_hierarchy(api_url, table_name, timeout)[0]


def _walk_hierarchy(
    api_url: str, table_name: str, timeout: int
) -> tuple[List[str], bool]:
    """The hierarchy, and whether the walk was refused part-way."""
    from servicenow_mcp.server import make_sn_request

    chain = [table_name]
    try:
        url = build_url(api_url, "table", "sys_db_object")
        response = make_sn_request(
            "GET",
            url,
            timeout,
            params={
                "sysparm_query": f"name={table_name}",
                "sysparm_fields": "name,super_class",
                "sysparm_limit": 1,
            },
        )
        rows = result_rows(parse_json_response(response, url))
        if not rows:
            return chain, False
        parent_id = _reference_value(rows[0].get("super_class"))
        depth = 0
        while parent_id and depth < MAX_DEPTH:
            url = build_url(api_url, "table", "sys_db_object", parent_id)
            response = make_sn_request(
                "GET", url, timeout, params={"sysparm_fields": "name,super_class"}
            )
            row = parse_json_response(response, url).get("result", {})
            name = row.get("name") if isinstance(row, dict) else None
            if not name or name in chain:
                break
            chain.append(name)
            parent_id = _reference_value(row.get("super_class"))
            depth += 1
    except ServiceNowAPIError as exc:
        logger.debug("super_class walk unavailable for %s: %s", table_name, exc)
        return chain, True
    return chain, False


def fetch_table_schema(
    table_name: str,
    *,
    limit: int,
    timeout: int,
    api_url: str,
    include_inherited: bool = True,
) -> Dict[str, Any]:
    """Return ``{"table", "hierarchy", "field_count", "fields"[, "truncated"]}``.

    Each table in the hierarchy is queried separately, direct table first,
    with a shrinking budget so inherited columns never crowd out the table's
    own columns when ``limit`` is reached.
    """
    from servicenow_mcp.server import make_sn_request

    hierarchy, walk_refused = (
        _walk_hierarchy(api_url, table_name, timeout)
        if include_inherited
        else ([table_name], False)
    )

    fields: List[Dict[str, Any]] = []
    truncated = False
    remaining = limit
    url = build_url(api_url, "table", "sys_dictionary")
    for table in hierarchy:
        if remaining <= 0:
            truncated = True
            break
        try:
            response = make_sn_request(
                "GET",
                url,
                timeout,
                params={
                    "sysparm_query": f"name={table}^internal_type!=collection",
                    "sysparm_fields": DICTIONARY_FIELDS,
                    "sysparm_limit": remaining,
                },
            )
        except ServiceNowAPIError as exc:
            if "(403)" not in str(exc):
                raise
            # The base system's sys_dictionary ACLs need personalize_dictionary
            # (admin includes it); itil and snc_read_only are not enough.
            raise ServiceNowAPIError(
                f"{exc} | Hint: reading table schemas (sys_dictionary) needs the "
                "personalize_dictionary role"
            ) from exc
        rows = result_rows(parse_json_response(response, url))
        kept = 0
        for row in rows:
            if not row.get("element"):
                continue
            fields.append(
                {
                    "name": row.get("element"),
                    "label": row.get("column_label"),
                    "type": row.get("internal_type"),
                    "max_length": row.get("max_length"),
                    "mandatory": row.get("mandatory"),
                    "reference": row.get("reference"),
                    "defined_in": row.get("name") or table,
                }
            )
            kept += 1
        if len(rows) >= remaining:
            # The server capped this page; anything further down the
            # hierarchy (or on this table) did not fit the budget.
            truncated = True
            remaining = 0
        else:
            remaining -= kept

    result: Dict[str, Any] = {
        "table": table_name,
        "hierarchy": hierarchy,
        "field_count": len(fields),
        "fields": fields,
    }
    if truncated:
        result["truncated"] = True
    if walk_refused:
        result["note"] = (
            "Parent tables could not be read (sys_db_object refused), so the "
            "hierarchy may be incomplete and inherited fields are missing."
        )
    return result
