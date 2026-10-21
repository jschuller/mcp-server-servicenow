"""Generic ServiceNow Table API tools.

Provides CRUD operations on any ServiceNow table via /api/now/table/{table_name}.
"""

import logging
import re
from typing import Annotated, Any, Dict, List, Literal, Optional, Tuple

from pydantic import Field

from servicenow_mcp.server import get_config, make_sn_request, mcp
from servicenow_mcp.tools import annotations
from servicenow_mcp.tools.results import RecordList
from servicenow_mcp.utils.http import build_url, parse_json_response, result_rows

logger = logging.getLogger(__name__)


ResponseFormat = Annotated[
    Literal["concise", "detailed"],
    Field(
        description=(
            "'detailed' (default) returns each reference field as {link, value}; "
            "'concise' drops the link (an instance URL) and returns the sys_id alone"
        )
    ),
]


def response_format_params(response_format: str) -> Dict[str, Any]:
    """Table API parameters for a list tool's ``response_format``."""
    if response_format == "concise":
        return {"sysparm_exclude_reference_link": "true"}
    return {}


DisplayValue = Annotated[
    Literal["false", "true", "all"],
    Field(
        description=(
            "'false' (default) returns stored values; 'true' returns labels in place "
            "of sys_ids and choice values; 'all' returns {display_value, value} per "
            "field, which keeps the sys_id beside the name. query= still filters on "
            "stored values, not labels. With 'true' or 'all', dates come back in this "
            "identity's time zone and format"
        )
    ),
]

GroupDisplayValue = Annotated[
    Literal["false", "true", "all"],
    Field(
        description=(
            "'false' (default) returns stored group_by values; 'true' returns labels "
            "in place of sys_ids and choice values; 'all' returns both. query= still "
            "filters on stored values, not labels"
        )
    ),
]


def display_value_params(display_value: str) -> Dict[str, Any]:
    """Table and Stats API parameters for a read tool's ``display_value``.

    "false" is the API default, so it sends nothing.
    """
    if display_value in ("true", "all"):
        return {"sysparm_display_value": display_value}
    return {}


# A term that starts with one of these names no field of the table: ordering,
# grouping, text search, and the brackets around related-list and sub-queries.
_QUERY_KEYWORDS = (
    "ORDERBY",  # also ORDERBYDESC
    "GROUPBY",
    "GOTO",
    "123TEXTQUERY321",
    "IR_",
    "RLQUERY",
    "ENDRLQUERY",
    "SUBQUERY",
    "ENDSUBQUERY",
)
# Column names are lowercase; a dot-walk joins them with ".". Operators are
# uppercase words or symbols, so the field is the leading lowercase run.
_QUERY_FIELD_RE = re.compile(r"[a-z0-9_]+(?:\.[a-z0-9_]+)*")
# A label ends where an operator starts: a symbol or an uppercase word.
_QUERY_LABEL_RE = re.compile(r"[A-Z][A-Za-z0-9_ .]*?(?=[A-Z]{2,}|[=!<>@]|$)")
# ^OR and ^NQ join a term, unless the term is a label such as ORIGIN: what
# follows the joiner is a field, a label like Name, or a keyword.
_QUERY_JOINER_RE = re.compile(
    r"(?:OR|NQ)(?:[a-z0-9_]|[A-Z][a-z]|" + "|".join(_QUERY_KEYWORDS) + r"|EQ\Z)"
)
# variables.<sys_id> and sys_tags.<sys_id> filter on catalog variables and
# tags: no row carries them as a key.
_PSEUDO_FIELDS = frozenset({"variables", "sys_tags"})
# A label is echoed in the warning, so it is cut short and keeps only the
# characters a label can hold: query text may come from a record.
_LABEL_MAX = 40
_LABEL_JUNK_RE = re.compile(r"[^A-Za-z0-9_ .]")
# More query fields than this are not checked: each one lengthens the URL.
_MAX_QUERY_FIELDS = 50


def query_field_names(query: Optional[str]) -> Tuple[List[str], List[str]]:
    """Return (field names, labels) that an encoded query filters on.

    Field names keep their dot-walk; only the first 50 are returned. Labels
    are terms that start with an uppercase letter and are no keyword, such as
    ``NameLIKEa``: no column is named that way, so the instance ignores the
    condition. Terms inside RLQUERY and SUBQUERY blocks filter another table
    and are skipped, and so are catalog variables and tags.
    """
    names: List[str] = []
    labels: List[str] = []
    if not query:
        return names, labels
    depth = 0
    # "^^" is an escaped caret inside a value, not a separator.
    for index, raw in enumerate(query.replace("^^", "\0").split("^")):
        term = raw.strip()
        if index and _QUERY_JOINER_RE.match(term) and not term.startswith("ORDERBY"):
            term = term[2:]
        if not term or term == "EQ":
            continue
        if term.startswith(("RLQUERY", "SUBQUERY")):
            depth += 1
            continue
        if term.startswith(("ENDRLQUERY", "ENDSUBQUERY")):
            depth = max(depth - 1, 0)
            continue
        if depth or term.startswith(_QUERY_KEYWORDS):
            continue
        field = _QUERY_FIELD_RE.match(term)
        if field:
            name = field.group().rstrip(".")
            if not _PSEUDO_FIELDS.intersection(name.split(".")):
                names.append(name)
        elif term[0].isupper():
            label = _QUERY_LABEL_RE.match(term)
            text = label.group().strip() if label else ""
            text = _LABEL_JUNK_RE.sub("", text if len(text) > 1 else term).strip()
            if len(text) > _LABEL_MAX:
                text = text[:_LABEL_MAX] + "..."
            labels.append(text)
    return list(dict.fromkeys(names))[:_MAX_QUERY_FIELDS], list(dict.fromkeys(labels))


def _field_list(fields: str) -> List[str]:
    return [name.strip() for name in fields.split(",") if name.strip()]


def fields_with_query_fields(
    fields: Optional[str], query_names: List[str]
) -> Tuple[Optional[str], List[str]]:
    """Add the query's field names to ``fields=`` so that the check sees them.

    Returns the ``sysparm_fields`` value and the names it added, which the
    caller removes from the rows again. Without ``fields=`` every readable
    field comes back, so nothing is added.
    """
    if not fields:
        return fields, []
    requested = set(_field_list(fields))
    added = [name for name in query_names if name not in requested]
    if not added:
        return fields, []
    return ",".join([fields.strip(), *added]), added


def drop_added_fields(records: List[Any], added: List[str]) -> None:
    """Remove the fields that ``fields_with_query_fields`` added from each row."""
    for row in records:
        if isinstance(row, dict):
            for name in added:
                row.pop(name, None)


def _add_order_clause(query: str, order_by: str) -> str:
    """Append a ServiceNow encoded-query order clause."""
    if order_by.startswith("-"):
        order_clause = f"ORDERBYDESC{order_by[1:]}"
    else:
        order_clause = f"ORDERBY{order_by}"

    return f"{query}^{order_clause}".lstrip("^")


def _missing_names(names: List[str], rows: List[Dict[str, Any]]) -> List[str]:
    return [
        name for name in dict.fromkeys(names) if not any(name in row for row in rows)
    ]


def _shown(names: List[str]) -> str:
    return ", ".join(names[:20]) + (
        f" and {len(names) - 20} more" if len(names) > 20 else ""
    )


def _missing_fields_warning(table_name: str, missing: List[str]) -> str:
    """The sentence that names requested fields no returned row carries.

    The Table API drops a field from every row both when the table has no such
    field and when an ACL hides it from the caller, and it silently ignores
    query conditions on hidden fields. The two cases look the same here, so the
    warning names both.
    """
    return (
        f"Fields missing from every row: {_shown(missing)}. They don't exist on "
        f"{table_name} or an ACL hides them from this identity; query conditions "
        "on them may have been ignored."
    )


def _plural(names: List[str], one: str, many: str) -> str:
    return one if len(names) == 1 else many


def list_warning(
    table_name: str,
    fields: Optional[str],
    query_names: List[str],
    labels: List[str],
    records: List[Any],
) -> Optional[str]:
    """The ``warning`` of list_records and list_ci, or None.

    The first sentence names requested fields that no row carries. The query's
    field names get their own sentences: with ``fields=`` they were added to
    the request (``fields_with_query_fields``), so each is checked whole.
    Without ``fields=`` the whole readable row comes back, so only each name's
    first dot-walk segment can be checked. A dot-walk that is missing although
    its reference was requested may only mean the referenced records are
    unreadable, so that case is hedged. Labels are reported even when no row
    comes back.
    """
    rows = [row for row in records if isinstance(row, dict)]
    requested = [name for name in _field_list(fields or "") if name not in query_names]
    missing_requested: List[str] = []
    ignored: List[str] = []
    walked: List[str] = []
    if rows:
        missing_requested = _missing_names(requested, rows)
        for name in query_names:
            base = name.split(".")[0]
            if not fields or "." not in name:
                if _missing_names([base if not fields else name], rows):
                    ignored.append(name)
            elif _missing_names([name], rows):
                walked.append(name)
    parts = (
        [_missing_fields_warning(table_name, missing_requested)]
        if missing_requested
        else []
    )
    if ignored:
        parts.append(
            f"query= filters on {_shown(ignored)}, which no row carries: the "
            "instance ignored "
            + _plural(ignored, "this condition", "these conditions")
            + ", so the rows may be unfiltered."
        )
    if walked:
        parts.append(
            f"query= filters on {_shown(walked)}, which no row carries: either the "
            "field doesn't exist or is hidden and the condition was ignored, or "
            "only the referenced records are unreadable and the condition applied. "
            "To tell, run the query again with a value that can't match: 0 rows "
            "means the condition applied."
        )
    if labels:
        effect = (
            "ignores "
            + _plural(labels, "this condition", "these conditions")
            + ", so the rows may be unfiltered"
            if rows
            else "ignored or rejected "
            + _plural(labels, "this condition", "these conditions")
        )
        parts.append(
            f"query= names {_shown(labels)}, which "
            + _plural(labels, "is not a column name", "are not column names")
            + f" (columns are lowercase, like short_description): the instance {effect}."
        )
    if ignored or labels:
        parts.append(
            "To find the real column name, call get_table_schema on the table "
            "that holds it (it needs personalize_dictionary), or read one row "
            "without fields= to see the readable columns."
        )
    return " ".join(parts) or None


@mcp.tool(tags={"read", "table"}, annotations=annotations.READ)
def list_records(
    table_name: Annotated[
        str,
        Field(
            description="The ServiceNow table name (e.g., 'sys_user', 'cmdb_ci_server', 'incident')"
        ),
    ],
    query: Annotated[
        Optional[str],
        Field(description="Encoded query string (e.g., 'active=true^priority=1')"),
    ] = None,
    fields: Annotated[
        Optional[str], Field(description="Comma-separated list of fields to return")
    ] = None,
    limit: Annotated[
        int, Field(ge=1, le=1000, description="Maximum number of records to return")
    ] = 20,
    offset: Annotated[int, Field(ge=0, description="Number of records to skip")] = 0,
    order_by: Annotated[
        Optional[str],
        Field(description="Field to order results by (prefix with '-' for descending)"),
    ] = None,
    response_format: ResponseFormat = "detailed",
    display_value: DisplayValue = "false",
) -> RecordList:
    """List records from any ServiceNow table with optional filtering, field selection, and pagination"""
    config = get_config()

    url = build_url(config.api_url, "table", table_name)
    query_params: Dict[str, Any] = {
        "sysparm_limit": limit,
        "sysparm_offset": offset,
    }
    query_names, labels = query_field_names(query)
    sysparm_fields, added = fields_with_query_fields(fields, query_names)
    if query:
        query_params["sysparm_query"] = query
    if sysparm_fields:
        query_params["sysparm_fields"] = sysparm_fields
    if order_by:
        query_params["sysparm_query"] = _add_order_clause(
            query_params.get("sysparm_query", ""), order_by
        )
    query_params.update(response_format_params(response_format))
    query_params.update(display_value_params(display_value))

    response = make_sn_request("GET", url, config.timeout, params=query_params)
    data = parse_json_response(response, url)
    result = result_rows(data)
    warning = list_warning(table_name, fields, query_names, labels, result)
    drop_added_fields(result, added)
    payload: RecordList = {"count": len(result), "records": result}
    if warning:
        payload["warning"] = warning
    return payload


@mcp.tool(tags={"read", "table"}, annotations=annotations.READ)
def get_record(
    table_name: Annotated[str, Field(description="The ServiceNow table name")],
    sys_id: Annotated[str, Field(description="The sys_id of the record")],
    fields: Annotated[
        Optional[str], Field(description="Comma-separated list of fields to return")
    ] = None,
    display_value: DisplayValue = "false",
) -> Dict[str, Any]:
    """Get a single record from a ServiceNow table by sys_id.

    If this is refused (401) while list_records works, call list_records with
    query="sys_id=<sys_id>" and limit=1 instead.
    """
    config = get_config()

    url = build_url(config.api_url, "table", table_name, sys_id)
    query_params: Dict[str, str] = {}
    if fields:
        query_params["sysparm_fields"] = fields
    query_params.update(display_value_params(display_value))

    response = make_sn_request("GET", url, config.timeout, params=query_params)
    data = parse_json_response(response, url)
    return data.get("result", {})


@mcp.tool(tags={"write", "table"}, annotations=annotations.CREATE)
def create_record(
    table_name: Annotated[str, Field(description="The ServiceNow table name")],
    data: Annotated[
        Dict[str, Any], Field(description="Record field values as key-value pairs")
    ],
) -> Dict[str, Any]:
    """Create a new record in any ServiceNow table"""
    config = get_config()

    url = build_url(config.api_url, "table", table_name)
    response = make_sn_request("POST", url, config.timeout, json_data=data)
    resp_data = parse_json_response(response, url)
    result = resp_data.get("result", {})
    return {"sys_id": result.get("sys_id"), "record": result}


@mcp.tool(tags={"write", "table"}, annotations=annotations.UPDATE)
def update_record(
    table_name: Annotated[str, Field(description="The ServiceNow table name")],
    sys_id: Annotated[str, Field(description="The sys_id of the record to update")],
    data: Annotated[
        Dict[str, Any], Field(description="Fields to update as key-value pairs")
    ],
) -> Dict[str, Any]:
    """Update an existing record in a ServiceNow table"""
    config = get_config()

    url = build_url(config.api_url, "table", table_name, sys_id)
    response = make_sn_request("PATCH", url, config.timeout, json_data=data)
    resp_data = parse_json_response(response, url)
    result = resp_data.get("result", {})
    return {"sys_id": result.get("sys_id"), "record": result}


@mcp.tool(tags={"write", "table"}, annotations=annotations.DELETE)
def delete_record(
    table_name: Annotated[str, Field(description="The ServiceNow table name")],
    sys_id: Annotated[str, Field(description="The sys_id of the record to delete")],
) -> Dict[str, Any]:
    """Delete a record from a ServiceNow table by sys_id"""
    config = get_config()

    url = build_url(config.api_url, "table", table_name, sys_id)
    make_sn_request("DELETE", url, config.timeout)
    return {"deleted": True, "table": table_name, "sys_id": sys_id}


@mcp.tool(tags={"read", "table"}, annotations=annotations.READ)
def aggregate_records(
    table_name: Annotated[
        str,
        Field(
            description="The ServiceNow table name (e.g., 'sys_user_group', 'cmdb_ci', 'incident')"
        ),
    ],
    count: Annotated[bool, Field(description="Include record count in results")] = True,
    avg_fields: Annotated[
        Optional[str],
        Field(
            description="Comma-separated fields to average (e.g., 'reassignment_count,reopen_count')"
        ),
    ] = None,
    min_fields: Annotated[
        Optional[str],
        Field(description="Comma-separated fields to find minimum values"),
    ] = None,
    max_fields: Annotated[
        Optional[str],
        Field(description="Comma-separated fields to find maximum values"),
    ] = None,
    sum_fields: Annotated[
        Optional[str], Field(description="Comma-separated fields to sum")
    ] = None,
    group_by: Annotated[
        Optional[str],
        Field(
            description="Comma-separated fields to group results by (e.g., 'priority,state')"
        ),
    ] = None,
    query: Annotated[
        Optional[str],
        Field(description="Encoded query string to filter records before aggregation"),
    ] = None,
    having: Annotated[
        Optional[str],
        Field(
            description=(
                "Post-aggregation filter, aggregate^field^operator^value "
                "(e.g., 'count^name^>^1')"
            )
        ),
    ] = None,
    display_value: GroupDisplayValue = "false",
) -> Dict[str, Any]:
    """Aggregate records using COUNT, AVG, MIN, MAX, SUM with optional GROUP BY via the Stats API.

    If the Stats API is refused (401) while list_records works, count with
    list_records instead: the same query, fields="sys_id", limit=1000, paging
    with offset.
    """
    config = get_config()

    url = build_url(config.api_url, "stats", table_name)
    query_params: Dict[str, Any] = {}

    if count:
        query_params["sysparm_count"] = "true"
    if avg_fields:
        query_params["sysparm_avg_fields"] = avg_fields
    if min_fields:
        query_params["sysparm_min_fields"] = min_fields
    if max_fields:
        query_params["sysparm_max_fields"] = max_fields
    if sum_fields:
        query_params["sysparm_sum_fields"] = sum_fields
    if group_by:
        query_params["sysparm_group_by"] = group_by
    if query:
        query_params["sysparm_query"] = query
    if having:
        query_params["sysparm_having"] = having
    query_params.update(display_value_params(display_value))

    response = make_sn_request("GET", url, config.timeout, params=query_params)
    data = parse_json_response(response, url)
    result = data.get("result", {})
    # Stats API returns a list when group_by is used, but a dict otherwise.
    # FastMCP requires tool return values to be dicts.
    if isinstance(result, list):
        return {"count": len(result), "groups": result}
    return result
