"""One WARNING line per ServiceNow API failure that reaches a client.

``ServiceNowAPIError`` is a FastMCP ``ToolError``: FastMCP returns its message
to the client as it is and logs no traceback. Over HTTP that message leaves
out the instance host and ServiceNow's diagnostic headers (``utils/http.py``),
so this middleware writes the headers and the low-level cause, with the parts
the client did get, to the server's log: one line, JSON after the prefix, never
a query string, response body content or a credential.

The line carries ``event`` (``tool_call`` or ``resource_read``), ``name`` (the
tool or the resource URI) and the error's ``details`` (without the hint) and
``diagnostics``. The ``details`` keys are the candidates for a structured error
field once the MCP specification defines one; until then the client gets them
as text only.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

from servicenow_mcp.utils.http import ServiceNowAPIError

logger = logging.getLogger(__name__)

LOG_PREFIX = "ServiceNow API error: "
MESSAGE_MAX_CHARS = 300


def _warn(event: str, name: str, exc: ServiceNowAPIError) -> None:
    record: dict[str, Any] = {"event": event, "name": name}
    # The hint is fixed text the client already has; the log line stays short.
    record.update({k: v for k, v in exc.details.items() if k != "hint"})
    record.update(exc.diagnostics)
    if not exc.details:
        # Raised with a message only: there is no request to describe.
        record["message"] = str(exc)[:MESSAGE_MAX_CHARS]
    payload = json.dumps(record, default=str, separators=(",", ":"))
    logger.warning(LOG_PREFIX + "%s", payload)


class ApiErrorMiddleware(Middleware):
    """Log each ``ServiceNowAPIError`` on its way to the client, then re-raise it."""

    async def on_call_tool(
        self, context: MiddlewareContext, call_next: CallNext
    ) -> Any:
        try:
            return await call_next(context)
        except ServiceNowAPIError as exc:
            _warn("tool_call", context.message.name, exc)
            raise

    async def on_read_resource(
        self, context: MiddlewareContext, call_next: CallNext
    ) -> Any:
        try:
            return await call_next(context)
        except ServiceNowAPIError as exc:
            _warn("resource_read", str(context.message.uri), exc)
            raise
