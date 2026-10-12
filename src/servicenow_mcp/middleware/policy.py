"""Policy middleware — identifier and query validation.

Everything here inspects *caller-supplied* tool arguments and resource URIs
before the tool body runs. Queries the server issues on its own behalf (for
example the ``user_name=javascript:gs.getUserName()`` lookup used for the
current user and for OAuth token verification) never pass through this
middleware and are unaffected.

Which tables and records a caller may read is ServiceNow's decision (ACLs, roles,
REST API access policies), not this module's: these checks only stop a tool
argument from rewriting a URL path or an encoded query.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

from servicenow_mcp.utils.config import ServerConfig


class PolicyError(ToolError):
    """Raised when a call violates the server's safety policy."""


# Table names, sys_ids and other identifiers that end up in URL paths or in
# encoded queries. ServiceNow identifiers are [a-z0-9_]; anything else (``/``,
# ``?``, ``^``, ``..``) is a traversal or query-injection attempt.
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_]+$")
ORDER_BY_RE = re.compile(r"^-?[A-Za-z0-9_.]+$")
FIELD_LIST_RE = re.compile(r"^\s*[A-Za-z0-9_.]+(\s*,\s*[A-Za-z0-9_.]+)*\s*$")
STATE_RE = re.compile(r"^[A-Za-z_ ]+$")

JS_PREFIX_RE = re.compile(r"javascript:", re.IGNORECASE)
# The only server-side script allowed in an encoded query: GlideSystem date
# helpers. Either a relative helper with a numeric (or empty) argument —
# gs.daysAgo(7), gs.daysAgoStart(1), gs.beginningOfToday(),
# gs.beginningOfLastWeek(), gs.monthsAgoStart(1), gs.nowDateTime() ... — or
# gs.dateGenerate() with a literal date and 'start', 'end' or a literal time,
# which is how the list UI writes ON and BETWEEN ranges. Each helper must end
# the value: at ``^``, at the ``@`` that separates the ends of a range, or at
# the end of the query.
_RELATIVE_DATE_HELPER = (
    r"gs\.(?:beginningOf|endOf|daysAgo|hoursAgo|minutesAgo|monthsAgo|yearsAgo|"
    r"quartersAgo|now|nowDateTime)[A-Za-z0-9]*\(\s*-?\d*\s*\)"
)
_DATE_GENERATE = (
    r"gs\.dateGenerate\(\s*['\"]\d{4}-\d{2}-\d{2}['\"]\s*,"
    r"\s*['\"](?:start|end|\d{2}:\d{2}:\d{2})['\"]\s*\)"
)
SAFE_JS_RE = re.compile(
    rf"javascript:(?:{_RELATIVE_DATE_HELPER}|{_DATE_GENERATE})(?=[\^@]|$)",
    re.IGNORECASE,
)

CLASS_TOOLS = frozenset({"list_ci", "get_ci", "create_ci", "update_ci"})
FIXED_TABLES: Dict[str, str] = {
    "get_ci_relationships": "cmdb_rel_ci",
    "get_current_user": "sys_user",
    "get_system_properties": "sys_properties",
    "list_update_sets": "sys_update_set",
    "get_update_set": "sys_update_set",
    "create_update_set": "sys_update_set",
    "set_current_update_set": "sys_update_set",
    "list_update_set_changes": "sys_update_xml",
}
IDENTIFIER_ARGS = ("sys_id", "update_set_sys_id", "relation_type")
FIELD_LIST_ARGS = (
    "fields",
    "group_by",
    "avg_fields",
    "min_fields",
    "max_fields",
    "sum_fields",
)
QUERY_ARGS = ("query", "having")
SCHEMA_URI_RE = re.compile(r"^servicenow://schema/(?P<table>[^/]+)$")


def _current_config() -> Optional[ServerConfig]:
    # Imported lazily: server.py registers this middleware at import time.
    try:
        from servicenow_mcp.server import get_config_or_none
    except Exception:
        return None
    return get_config_or_none()


def resolve_table(tool_name: str, arguments: Dict[str, Any]) -> Optional[str]:
    """Return the ServiceNow table a tool call targets, or None if unknown."""
    table = arguments.get("table_name")
    if isinstance(table, str):
        return table
    if tool_name in CLASS_TOOLS:
        class_name = arguments.get("class_name")
        return class_name if isinstance(class_name, str) else "cmdb_ci"
    return FIXED_TABLES.get(tool_name)


def check_identifier(name: str, value: Any) -> None:
    """Reject identifiers that could rewrite a URL path or an encoded query."""
    if value is None:
        return
    if not isinstance(value, str) or not IDENTIFIER_RE.match(value):
        raise PolicyError(
            f"Invalid {name} {str(value)[:60]!r}: only letters, digits and "
            "underscores are allowed"
        )


def find_unsafe_js(value: str) -> Optional[str]:
    """Return the first unsafe ``javascript:`` expression in *value*, or None.

    Every occurrence is checked — a safe helper earlier in the query does not
    excuse an unsafe one later.
    """
    for match in JS_PREFIX_RE.finditer(value):
        if not SAFE_JS_RE.match(value, match.start()):
            return value[match.start() : match.start() + 80]
    return None


def check_query(name: str, value: Any, config: ServerConfig) -> None:
    """Reject caller-supplied encoded queries containing arbitrary server-side script."""
    if value is None or config.allow_js_queries:
        return
    if not isinstance(value, str):
        return
    offending = find_unsafe_js(value)
    if offending is not None:
        raise PolicyError(
            f"Query rejected: unsafe javascript: expression in {name} "
            f"({offending!r}). Only GlideSystem date helpers such as "
            "javascript:gs.daysAgo(7), javascript:gs.beginningOfToday() or "
            "javascript:gs.dateGenerate('2026-10-01','start') are allowed; use the "
            "RELATIVE* operators or ON/BETWEEN ranges instead (servicenow://help/query-syntax), "
            "or start the server with --allow-js-queries (SERVICENOW_ALLOW_JS_QUERIES=true)."
        )


def validate_tool_call(
    tool_name: str, arguments: Dict[str, Any], config: ServerConfig
) -> None:
    """Apply every policy check to one tool invocation."""
    table = resolve_table(tool_name, arguments)
    if table is not None:
        check_identifier("table name", table)

    for arg in IDENTIFIER_ARGS:
        if arg in arguments:
            check_identifier(arg, arguments[arg])

    state = arguments.get("state")
    if state is not None and (not isinstance(state, str) or not STATE_RE.match(state)):
        raise PolicyError(f"Invalid state {str(state)[:60]!r}")

    order_by = arguments.get("order_by")
    if order_by is not None and (
        not isinstance(order_by, str) or not ORDER_BY_RE.match(order_by)
    ):
        raise PolicyError(
            f"Invalid order_by {str(order_by)[:60]!r}: expected a field name, "
            "optionally prefixed with '-'"
        )

    for arg in FIELD_LIST_ARGS:
        value = arguments.get(arg)
        if value is not None and (
            not isinstance(value, str) or not FIELD_LIST_RE.match(value)
        ):
            raise PolicyError(
                f"Invalid {arg} {str(value)[:60]!r}: expected a comma-separated "
                "list of field names"
            )

    for arg in QUERY_ARGS:
        if arg in arguments:
            check_query(arg, arguments[arg], config)


class PolicyMiddleware(Middleware):
    """Validate identifiers and harden caller queries on every call."""

    async def on_call_tool(
        self, context: MiddlewareContext, call_next: CallNext
    ) -> Any:
        config = _current_config()
        if config is not None:
            validate_tool_call(
                context.message.name, dict(context.message.arguments or {}), config
            )
        return await call_next(context)

    async def on_read_resource(
        self, context: MiddlewareContext, call_next: CallNext
    ) -> Any:
        match = SCHEMA_URI_RE.match(str(context.message.uri))
        if match:
            check_identifier("table name", match.group("table"))
        return await call_next(context)
