"""Result shapes of the read tools that return a list envelope.

FastMCP publishes each as the tool's ``outputSchema``, so a client can rely on
the keys. Keep them minimal: records are whatever the instance returns, so
only the envelope is typed. ``truncated``, ``next_offset`` and ``note`` are set by
the response limiter when it cuts a list to fit the size limit
(``middleware/response_limit.py``); ``LIST_KEYS`` tells it which key to cut.

``typing_extensions.TypedDict`` because pydantic refuses ``typing.TypedDict``
on Python < 3.12.
"""

from typing import Any, Dict, List

from typing_extensions import NotRequired, TypedDict

Row = Dict[str, Any]


class RecordList(TypedDict):
    count: int
    records: List[Row]
    warning: NotRequired[str]
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


# Tool name -> the list the limiter may cut, and whether the tool pages with
# ``offset`` (then a cut result says where to continue).
LIST_KEYS: Dict[str, tuple[str, bool]] = {
    "list_records": ("records", True),
    "list_ci": ("records", True),
    "get_ci_relationships": ("relationships", True),
    "get_system_properties": ("properties", False),
    "list_update_sets": ("update_sets", False),
    "list_update_set_changes": ("changes", False),
    "get_table_schema": ("fields", False),
    "find_references": ("groups", False),
}
