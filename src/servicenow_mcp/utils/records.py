"""The ``result`` of a ServiceNow answer, checked for its shape.

A tool that returns a record hands FastMCP an object; anything else (a string,
a list, null) would be refused there with an error that quotes it. These
helpers say what was wrong by type only: the content of an unexpected answer
is never repeated, since it can hold what a tool would have withheld.
"""

from __future__ import annotations

from typing import Any, Dict, List

from servicenow_mcp.utils.http import ServiceNowAPIError

_KINDS = {
    dict: "an object",
    list: "a list",
    str: "a string",
    bool: "a boolean",
    int: "a number",
    float: "a number",
    type(None): "null",
}


def _kind(value: Any) -> str:
    return _KINDS.get(type(value), "a value of another type")


def _unexpected(data: Any, wanted: str) -> ServiceNowAPIError:
    if not isinstance(data, dict):
        got = f"{_kind(data)} as the whole answer"
    elif "result" not in data:
        got = "an answer without a result"
    elif isinstance(data["result"], list):
        got = "a list that holds something other than objects"
        if all(isinstance(item, dict) for item in data["result"]):
            got = "a list of objects"
    else:
        got = f"{_kind(data['result'])} as the result"
    return ServiceNowAPIError(
        f"Unexpected answer from ServiceNow: {got}, where {wanted} was expected. "
        "Its content is not shown."
    )


def record_result(data: Any) -> Dict[str, Any]:
    """The ``result`` of a single-record call: an object, or an error."""
    result = data.get("result") if isinstance(data, dict) else None
    if isinstance(result, dict):
        return result
    raise _unexpected(data, "one record")


def stats_result(data: Any) -> Any:
    """The ``result`` of a Stats API call: an object, or a list of objects
    when the call groups."""
    result = data.get("result") if isinstance(data, dict) else None
    if isinstance(result, dict):
        return result
    if isinstance(result, list) and all(isinstance(item, dict) for item in result):
        return result
    raise _unexpected(data, "statistics")


def first_row(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The first of ``result_rows``, or an empty object."""
    return rows[0] if rows else {}
