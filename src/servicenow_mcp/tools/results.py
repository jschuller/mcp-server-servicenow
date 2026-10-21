"""Result shapes of the read tools that return a list envelope.

FastMCP publishes each as the tool's ``outputSchema``, so a client can rely on
the keys. Keep them minimal: records are whatever the instance returns, so
only the envelope is typed. ``display_note`` says which time zone display
values use. ``truncated``, ``next_offset`` and ``note`` are set by
the response limiter when it cuts a list to fit the size limit
(``middleware/response_limit.py``); ``LIST_KEYS`` tells it which key to cut.

``typing_extensions.TypedDict`` because pydantic refuses ``typing.TypedDict``
on Python < 3.12.
"""

from typing import Any, Dict, List, NamedTuple, Optional

from typing_extensions import NotRequired, TypedDict

Row = Dict[str, Any]


class RecordList(TypedDict):
    count: int
    records: List[Row]
    warning: NotRequired[str]
    display_note: NotRequired[str]
    truncated: NotRequired[bool]
    note: NotRequired[str]
    next_offset: NotRequired[int]


# "class" is a keyword, so this one is spelled the functional way.
CIList = TypedDict(
    "CIList",
    {
        "count": int,
        "class": str,
        "records": List[Row],
        "warning": NotRequired[str],
        "display_note": NotRequired[str],
        "truncated": NotRequired[bool],
        "note": NotRequired[str],
        "next_offset": NotRequired[int],
    },
)


class RelationshipList(TypedDict):
    count: int
    relationships: List[Row]
    truncated: NotRequired[bool]
    note: NotRequired[str]
    next_offset: NotRequired[int]


class PropertyList(TypedDict):
    count: int
    properties: List[Row]
    truncated: NotRequired[bool]
    note: NotRequired[str]


class UpdateSetList(TypedDict):
    count: int
    update_sets: List[Row]
    truncated: NotRequired[bool]
    note: NotRequired[str]


class UpdateSetChangeList(TypedDict):
    count: int
    changes: List[Row]
    truncated: NotRequired[bool]
    note: NotRequired[str]


class TableSchema(TypedDict):
    table: str
    hierarchy: List[str]
    field_count: int
    fields: List[Row]
    truncated: NotRequired[bool]
    note: NotRequired[str]


class ReferenceGroup(TypedDict):
    source: str
    table: str
    count: int
    complete: bool
    items: List[Row]


class NotAssessable(TypedDict):
    source: str
    table: str
    reason: str


class ReferenceReport(TypedDict):
    table: str
    field: NotRequired[str]
    groups: List[ReferenceGroup]
    not_assessable: List[NotAssessable]
    truncated: NotRequired[bool]
    note: NotRequired[str]


class ListKey(NamedTuple):
    """How the response limiter cuts one list tool's result."""

    key: str  # the list it may cut
    pages: bool  # the tool takes ``offset``, so a cut says where to continue
    count_key: Optional[str]  # holds len(key); rewritten after a cut
    narrow: str  # what a caller can do when not even one item fits


LIST_KEYS: Dict[str, ListKey] = {
    "list_records": ListKey("records", True, "count", "ask for fewer fields (fields=)"),
    "list_ci": ListKey("records", True, "count", "ask for fewer fields (fields=)"),
    "get_ci_relationships": ListKey(
        "relationships", True, "count", "skip it with offset=next_offset+1"
    ),
    "get_system_properties": ListKey("properties", False, "count", "narrow the query"),
    "list_update_sets": ListKey("update_sets", False, "count", "narrow the query"),
    "list_update_set_changes": ListKey(
        "changes", False, "count", "read the changes with list_records and fields="
    ),
    "get_table_schema": ListKey(
        "fields", False, "field_count", "lower limit= or set include_inherited=false"
    ),
    "find_references": ListKey("groups", False, None, "lower limit="),
}
