"""Generic ServiceNow Table API tools.

Provides CRUD operations on any ServiceNow table via /api/now/table/{table_name}.
"""

import logging
import re
from typing import Annotated, Any, Dict, List, Literal, Optional, Tuple

from pydantic import Field

from servicenow_mcp.middleware.read_only_identity import caller_claims
from servicenow_mcp.server import get_config, make_sn_request, mcp
from servicenow_mcp.tools import annotations
from servicenow_mcp.tools.results import RecordList
from servicenow_mcp.utils.http import build_url, parse_json_response, result_rows
from servicenow_mcp.utils.user import has_role

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


# Display values carry no time-zone marker, so a list that returns them says
# which zone they are in. The zone's name is often unknowable: the caller's
# sys_user.time_zone is usually empty and glide.sys.default.tz needs admin.
DISPLAY_NOTE = (
    "Display values use this identity's time zone and date format (the "
    "instance default when the user has none; see servicenow://instance). "
    'Stored date-time values are UTC; display_value="all" shows both. In '
    "query=, gs.dateGenerate() and the gs.beginningOf* helpers use this "
    "identity's time zone."
)


def display_note(display_value: str, records: List[Any]) -> Optional[str]:
    """The ``display_note`` of a list tool, or None."""
    if display_value in ("true", "all") and records:
        return DISPLAY_NOTE
    return None


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
# The instance trims ASCII whitespace and control characters (<= U+0020)
# around a name, as Java's trim() does, and nothing else.
_TRIM = "".join(chr(code) for code in range(0x21))
# Column names are lowercase; a dot-walk joins them with ".". Operators are
# uppercase words or symbols, so a field term is a lowercase run, optional
# trimmed whitespace, then an operator. A term that starts with an uppercase
# letter and is no keyword (a label like Name) names no column. Anything
# else is not checked: the server can't tell what the instance makes of it.
_QUERY_FIELD_RE = re.compile(
    r"([a-z0-9_]+(?:\.[a-z0-9_]+)*)(?=[\x00-\x20]*(?:[A-Z=!<>@]|\Z))"
)
# ^OR and ^NQ join a term, unless the term is a label such as ORIGIN: what
# follows the joiner is a field, a label like Name, or a keyword.
_QUERY_JOINER_RE = re.compile(
    r"(?:OR|NQ)[\x00-\x20]*(?:[a-z0-9_]|[A-Z][a-z]|"
    + "|".join(_QUERY_KEYWORDS)
    + r"|EQ\Z)"
)
# variables.<sys_id> and sys_tags.<sys_id> filter on catalog variables and
# tags: no row carries them as a key.
_PSEUDO_FIELDS = frozenset({"variables", "sys_tags"})
# More query fields than this are not checked: each one lengthens the URL.
_MAX_QUERY_FIELDS = 50


def query_field_names(query: Optional[str]) -> Tuple[List[str], int]:
    """Return the field names an encoded query filters on, and how many terms
    name no column.

    Field names keep their dot-walk; only the first 50 are returned. A term
    that starts with an uppercase letter and is no keyword, such as
    ``NameLIKEa``, matches no column, so the instance ignores the condition.
    Only the number of such terms is returned: the warning never echoes them,
    since query text may come from a record. Terms inside RLQUERY and SUBQUERY
    blocks filter another table and are skipped, and so are catalog variables,
    tags and any term the server can't parse.
    """
    names: List[str] = []
    unknown = 0
    if not query:
        return names, unknown
    depth = 0
    # "^^" is an escaped caret inside a value, not a separator. Its
    # placeholder is a private-use character: nothing trims it and no field
    # name holds it.
    for index, raw in enumerate(query.replace("^^", "\ue000").split("^")):
        term = raw.strip(_TRIM)
        if index and _QUERY_JOINER_RE.match(term) and not term.startswith("ORDERBY"):
            term = term[2:].strip(_TRIM)
        if not term or term in ("EQ", "OR", "NQ"):
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
            if not _PSEUDO_FIELDS.intersection(field.group(1).split(".")):
                names.append(field.group(1))
        elif "A" <= term[0] <= "Z":
            unknown += 1
    return list(dict.fromkeys(names))[:_MAX_QUERY_FIELDS], unknown


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


_ECHO_RE = re.compile(r"[A-Za-z0-9_.]+")


def _echo(name: str) -> str:
    if not _ECHO_RE.fullmatch(name):
        return "(a name that is not a column name)"
    return name if len(name) <= 60 else name[:60] + "..."


def _shown(names: List[str]) -> str:
    """Names for the warning: field-name characters only, at most 60 each."""
    shown = [_echo(name) for name in names[:20]]
    return ", ".join(shown) + (
        f" and {len(names) - 20} more" if len(names) > 20 else ""
    )


def _missing_fields_warning(table_name: str, missing: List[str]) -> str:
    """The sentence that names requested fields no returned row carries.

    The Table API drops a field from every row both when the table has no such
    field and when an ACL hides it from the caller, and it silently ignores
    query conditions on hidden fields. The two cases look the same here, so the
    warning names both. A field of a table that extends this one (a CMDB
    subclass, a task type) is in neither case but looks the same.
    """
    example = ", such as a CMDB subclass," if table_name.startswith("cmdb") else ""
    return (
        f"Fields missing from every row: {_shown(missing)}. They don't exist on "
        f"{table_name} (a field defined on a table that extends {table_name}"
        f"{example} comes back only when you query that table) or an ACL hides "
        "them from this identity; query conditions on them may have been ignored."
    )


def _plural(names: List[str], one: str, many: str) -> str:
    return one if len(names) == 1 else many


def list_warning(
    table_name: str,
    fields: Optional[str],
    query_names: List[str],
    unknown: int,
    records: List[Any],
) -> Optional[str]:
    """The ``warning`` of list_records and list_ci, or None.

    The first sentence names requested fields that no row carries. The query's
    field names get their own sentences: with ``fields=`` they were added to
    the request (``fields_with_query_fields``), so each is checked whole.
    Without ``fields=`` the whole readable row comes back, so only each name's
    first dot-walk segment can be checked. A dot-walk that is missing although
    its reference came back may only mean the referenced records are
    unreadable, so that case is hedged. Terms that name no column are
    counted, not echoed, and reported even when no row comes back.
    """
    rows = [row for row in records if isinstance(row, dict)]
    requested = [name for name in _field_list(fields or "") if name not in query_names]
    missing_requested: List[str] = []
    ignored: List[str] = []
    walked: List[str] = []
    if rows:
        missing_requested = _missing_names(requested, rows)
        # References no row carries, requested or filtered on: nothing to walk.
        missing_plain = set(missing_requested) | set(
            _missing_names([name for name in query_names if "." not in name], rows)
        )
        for name in query_names:
            base = name.split(".")[0]
            if not fields or "." not in name:
                if _missing_names([base if not fields else name], rows):
                    ignored.append(name)
            elif _missing_names([name], rows):
                (ignored if base in missing_plain else walked).append(name)
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
    if unknown:
        one = unknown == 1
        conditions = "this condition" if one else "these conditions"
        effect = (
            f"The instance ignores {conditions}, so the rows may be unfiltered."
            if rows
            else f"The instance ignored or rejected {conditions}."
        )
        parts.append(
            f"query= has {unknown} "
            + ("term that starts" if one else "terms that start")
            + " with an uppercase letter, such as a form label like Name. Column"
            f" names are lowercase, like short_description. {effect}"
        )
    if ignored or unknown:
        parts.append(
            "To find the real column name, call get_table_schema on the table "
            "that holds it (it needs personalize_dictionary), or read one row "
            "without fields= to see the readable columns."
        )
    return " ".join(parts) or None


# Journal and audit tables hide their rows from an identity that may not read
# them: a read can return 0 rows, not a 403, so "no history" and "not allowed
# to see it" look the same. Reading them needs admin or audit_viewer. Not
# sys_history_set/line: they are a cache built on demand, so 0 rows there
# usually means no cache.
_HISTORY_TABLES = ("sys_journal_field", "sys_audit")
_HISTORY_ROLES = ("admin", "audit_viewer")
_ROLE_LOOKUP_TIMEOUT = 5
# (config the answer belongs to, answer): the service account's definite
# answer, as ReadOnlyIdentityMiddleware keeps its own. Per-user OAuth tokens
# are not cached: each caller is asked.
_history_reader: Tuple[Any, Optional[bool]] = (None, None)


def _reads_history(config: Any) -> Optional[bool]:
    """Whether the caller holds admin or audit_viewer, or None if unknown.

    False means no grant is visible: the caller's own role rows could also
    be hidden without a 403.
    """
    global _history_reader
    service_account = caller_claims() is None
    cached_for, cached = _history_reader
    if service_account and cached_for is config and cached is not None:
        return cached
    answers = []
    for role in _HISTORY_ROLES:
        answer = has_role(
            config.api_url, min(config.timeout, _ROLE_LOOKUP_TIMEOUT), role
        )
        if answer:
            break
        answers.append(answer)
    reads = True if answer else (None if None in answers else False)
    if service_account and reads is not None:
        _history_reader = (config, reads)
    return reads


def history_warning(
    table_name: str, records: List[Any], offset: int, config: Any
) -> Optional[str]:
    """The warning for 0 rows from a journal or audit table, or None.

    Fires only on the first page, and only when the caller is not known to
    hold a role that can read the table: with one, 0 rows means empty.
    """
    if table_name not in _HISTORY_TABLES or records or offset:
        return None
    reads = _reads_history(config)
    if reads:
        return None
    if table_name == "sys_audit":
        # Seen as a 403 without the roles, so 0 rows may also be no changes.
        return (
            "0 rows may mean this identity can't read sys_audit rows (that needs "
            "admin or audit_viewer): say that no field changes are visible to this "
            "identity, not that there are none."
        )
    if reads is False:
        opening = (
            "0 rows: no admin or audit_viewer grant is visible to this identity, "
            "and the instance hides journal rows from identities without one "
            "instead of refusing, so "
        )
    else:
        opening = (
            "0 rows may mean this identity can't read journal rows (that needs "
            "admin or audit_viewer): then "
        )
    return opening + (
        "the journal entries asked for are not assessable here, not empty. "
        "A record's own journal fields still show every entry with its time "
        "and author: list_records on the record's table with query=\"sys_id="
        '<sys_id>", fields="work_notes,comments" and display_value="true".'
    )


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
    query_names, unknown = query_field_names(query)
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
    warnings = [
        list_warning(table_name, fields, query_names, unknown, result),
        history_warning(table_name, result, offset, config),
    ]
    drop_added_fields(result, added)
    payload: RecordList = {"count": len(result), "records": result}
    warning = " ".join(text for text in warnings if text)
    if warning:
        payload["warning"] = warning
    note = display_note(display_value, result)
    if note:
        payload["display_note"] = note
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
