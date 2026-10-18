"""A response limiter that keeps structured results valid.

FastMCP's ``ResponseLimitingMiddleware`` cuts an oversized result to text and
drops ``structuredContent``, so it also hides every ``outputSchema`` (a client
that validates would reject a schema'd tool's text-only result). For the list
tools in ``LIST_KEYS`` this subclass publishes the schema and, when a result is
too big, drops trailing list items instead: the result keeps its shape and
says ``truncated: true`` (plus ``next_offset`` for tools that page), which
tells the agent how to get the rest. Every other tool keeps the parent's
behaviour.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

import mcp_types as mt
import pydantic_core
from fastmcp.server.middleware.middleware import CallNext, MiddlewareContext
from fastmcp.server.middleware.response_limiting import ResponseLimitingMiddleware
from fastmcp.tools.base import InputRequiredToolResult, Tool, ToolResult
from mcp_types import TextContent

logger = logging.getLogger(__name__)

# The audit log reads this from the result's meta to mark a cut response.
TRUNCATED_META = "io.github.jschuller/truncated"


class StructuredResponseLimiter(ResponseLimitingMiddleware):
    def __init__(
        self,
        *,
        list_keys: Mapping[str, tuple[str, bool]],
        max_size: int,
        truncation_suffix: str,
    ) -> None:
        super().__init__(max_size=max_size, truncation_suffix=truncation_suffix)
        self.list_keys = dict(list_keys)

    async def on_list_tools(
        self,
        context: MiddlewareContext[mt.ListToolsRequest],
        call_next: CallNext[mt.ListToolsRequest, Sequence[Tool]],
    ) -> Sequence[Tool]:
        tools = await call_next(context)
        return [
            tool
            if tool.name in self.list_keys or tool.output_schema is None
            else tool.model_copy(update={"output_schema": None})
            for tool in tools
        ]

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        name = context.message.name
        if name not in self.list_keys:
            return await super().on_call_tool(context, call_next)
        result = await call_next(context)
        if isinstance(result, InputRequiredToolResult) or not isinstance(
            result, ToolResult
        ):
            return result
        if len(pydantic_core.to_json(result, fallback=str)) <= self.max_size:
            return result
        key, pages = self.list_keys[name]
        payload = result.structured_content
        items = payload.get(key) if isinstance(payload, dict) else None
        offset = (context.message.arguments or {}).get("offset", 0)
        cut = (
            self._cut(result, payload, key, items, offset if pages else None)
            if isinstance(payload, dict) and isinstance(items, list)
            else None
        )
        if cut is None:
            # Not even one item fits: fall back to the text cut.
            return self._truncate_to_result(
                "\n\n".join(
                    b.text for b in result.content if isinstance(b, TextContent)
                ),
                meta=result.meta,
                is_error=result.is_error,
            )
        logger.warning(
            "Tool %r response exceeds size limit (%d bytes): kept %d of %d %s",
            name,
            self.max_size,
            len(cut.structured_content[key]),  # type: ignore[index]
            len(items),  # type: ignore[arg-type]
            key,
        )
        return cut

    def _cut(
        self,
        result: ToolResult,
        payload: dict[str, Any],
        key: str,
        items: list[Any],
        offset: int | None,
    ) -> ToolResult | None:
        """The largest prefix of ``items`` whose result fits, or None."""

        def build(n: int) -> ToolResult:
            trimmed = {**payload, key: items[:n], "truncated": True}
            if "count" in payload:
                trimmed["count"] = n
            if offset is not None:
                trimmed["next_offset"] = offset + n
            return ToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=pydantic_core.to_json(trimmed, fallback=str).decode(),
                    )
                ],
                structured_content=trimmed,
                meta={**(result.meta or {}), TRUNCATED_META: True},
                is_error=result.is_error,
            )

        def fits(n: int) -> bool:
            return len(pydantic_core.to_json(build(n), fallback=str)) <= self.max_size

        high = len(items) - 1  # the full list is known not to fit
        if high < 1 or not fits(1):
            return None
        low = 1
        while low < high:
            mid = (low + high + 1) // 2
            if fits(mid):
                low = mid
            else:
                high = mid - 1
        return build(low)
