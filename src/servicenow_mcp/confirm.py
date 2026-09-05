"""Opt-in confirmation for destructive tool calls (``--write-confirm``).

Two MCP eras need two mechanisms:

* Handshake-era connections (≤ 2025-11-25, e.g. Claude Code on stdio) support
  server-initiated ``elicitation/create``; we call ``ctx.elicit()``.
* 2026-07-28 connections replace that with multi round-trip requests: the
  tool *returns* an ``InputRequiredResult`` and is re-invoked with
  ``ctx.input_responses`` once the client has an answer.

Clients that cannot show a prompt (Claude Desktop/Cowork answer with a
synthetic ``cancel``; claude.ai connectors and headless runs declare no
elicitation capability) fall back to the explicit ``confirm=true`` argument.
A human *decline* is final and is never turned into a retry hint.
"""

from __future__ import annotations

import json
from contextvars import ContextVar
from typing import Any, Dict, List, Optional

from fastmcp import Context
from fastmcp.exceptions import ToolError
from fastmcp.server.elicitation import (
    AcceptedElicitation,
    CancelledElicitation,
    DeclinedElicitation,
    parse_elicit_response_type,
)
from mcp.shared.exceptions import MCPError
from mcp.types import (
    ClientCapabilities,
    ElicitationCapability,
    ElicitRequest,
    ElicitRequestFormParams,
    InputRequiredResult,
)
from mcp.types.version import MODERN_PROTOCOL_VERSIONS

CONFIRM_ARG_DESCRIPTION = (
    "Acknowledge this destructive change. Only consulted when the server runs "
    "with --write-confirm and the client cannot show a confirmation dialog; "
    "ignored otherwise."
)

# How the last confirmation was resolved — read by the audit middleware.
# off | prompted | arg | unsupported | required | declined
CONFIRM_OUTCOME: ContextVar[Optional[str]] = ContextVar(
    "servicenow_mcp_confirm_outcome", default=None
)

ELICIT_KEY = "confirm"


class ConfirmationRequired(ToolError):
    """The client cannot prompt and the call did not pass ``confirm=true``."""


class DeclinedByUser(ToolError):
    """The user declined the confirmation prompt."""


def _write_confirm_enabled() -> bool:
    from servicenow_mcp.server import get_config_or_none

    config = get_config_or_none()
    return bool(config and config.write_confirm)


def _is_modern(ctx: Context) -> bool:
    try:
        request_context = ctx.request_context
        if request_context is None:
            return False
        return request_context.protocol_version in MODERN_PROTOCOL_VERSIONS
    except Exception:
        try:
            return bool(ctx._is_modern_protocol())
        except Exception:
            return False


def _client_declared_elicitation(ctx: Context) -> bool:
    try:
        return bool(
            ctx.session.check_client_capability(
                ClientCapabilities(elicitation=ElicitationCapability())
            )
        )
    except Exception:
        return False


def _format_message(
    action: str, table: str, sys_id: str, preview: Dict[str, Any]
) -> str:
    lines = [f"{action} {table}/{sys_id}?"]
    if preview:
        lines.append("")
        for key, value in preview.items():
            lines.append(f"  {key}: {value}")
    return "\n".join(lines)


def _bool_request(message: str, request_state: str) -> InputRequiredResult:
    """Build the 2026-07-28 multi round-trip elicitation for a yes/no answer."""
    schema = parse_elicit_response_type(bool).schema
    return InputRequiredResult(
        input_requests={
            ELICIT_KEY: ElicitRequest(
                params=ElicitRequestFormParams(message=message, requested_schema=schema)
            )
        },
        request_state=request_state,
    )


def _fallback(
    *, confirm_arg: bool, action: str, table: str, sys_id: str, preview: Dict[str, Any]
) -> Optional[InputRequiredResult]:
    """Explicit-argument tier: proceed on ``confirm=true``, otherwise raise."""
    if confirm_arg:
        CONFIRM_OUTCOME.set("arg")
        return None
    CONFIRM_OUTCOME.set("required")
    payload = {
        "error": "confirmation_required",
        "action": action,
        "table": table,
        "sys_id": sys_id,
        "preview": preview,
        "hint": (
            "This client could not show a confirmation dialog (Claude Desktop/"
            "Cowork, claude.ai connectors and headless runs cannot). Show the "
            "preview to the user, then re-run with confirm=true — or start the "
            "server without --write-confirm."
        ),
    }
    raise ConfirmationRequired(json.dumps(payload))


def _declined() -> DeclinedByUser:
    CONFIRM_OUTCOME.set("declined")
    return DeclinedByUser(
        "Declined by user: the confirmation prompt was answered 'no'. "
        "Do not retry without asking the user."
    )


async def confirm_destructive(
    ctx: Context,
    *,
    action: str,
    table: str,
    sys_id: str,
    preview: Dict[str, Any],
    confirm_arg: bool,
) -> Optional[InputRequiredResult]:
    """Return ``None`` to proceed, an ``InputRequiredResult`` to ask, or raise.

    Never returns a falsy "go ahead" that could be confused with the ask —
    refusal always raises (``DeclinedByUser`` / ``ConfirmationRequired``).
    """
    if not _write_confirm_enabled():
        CONFIRM_OUTCOME.set("off")
        return None

    message = _format_message(action, table, sys_id, preview)

    def fallback() -> Optional[InputRequiredResult]:
        return _fallback(
            confirm_arg=confirm_arg,
            action=action,
            table=table,
            sys_id=sys_id,
            preview=preview,
        )

    if _is_modern(ctx):
        responses = ctx.input_responses or {}
        response = responses.get(ELICIT_KEY)
        if response is not None:
            answer = getattr(response, "action", None)
            if answer == "accept":
                content = getattr(response, "content", None) or {}
                if isinstance(content, dict) and content.get("value") is True:
                    CONFIRM_OUTCOME.set("prompted")
                    return None
                raise _declined()
            if answer == "decline":
                raise _declined()
            # "cancel": the client dismissed or could not render the prompt.
            return fallback()
        if not _client_declared_elicitation(ctx):
            # Spec: servers MUST NOT send inputRequests the client has not
            # declared support for.
            return fallback()
        CONFIRM_OUTCOME.set("prompted")
        return _bool_request(message, f"{action}:{table}:{sys_id}")

    # Handshake era: server-initiated elicitation.
    if not _client_declared_elicitation(ctx):
        return fallback()
    try:
        result = await ctx.elicit(
            message, response_type=bool, response_title=f"Confirm {action.lower()}"
        )
    except MCPError:
        return fallback()

    if isinstance(result, AcceptedElicitation):
        if result.data is True:
            CONFIRM_OUTCOME.set("prompted")
            return None
        raise _declined()
    if isinstance(result, DeclinedElicitation):
        raise _declined()
    if isinstance(result, CancelledElicitation):
        return fallback()
    raise _declined()


async def fetch_preview(url: str, timeout: int, fields: List[str]) -> Dict[str, Any]:
    """GET the record's current values for the confirmation message.

    Only called when ``--write-confirm`` is on; a failure here must not mask
    the write's own error, so it degrades to a note instead of raising.
    """
    from servicenow_mcp.server import make_sn_request_async
    from servicenow_mcp.utils.http import parse_json_response

    wanted = ["sys_id", "number", "name", *fields]
    params = {"sysparm_fields": ",".join(dict.fromkeys(wanted))}
    try:
        response = await make_sn_request_async("GET", url, timeout, params=params)
        record = parse_json_response(response, url).get("result", {})
    except Exception as exc:  # pragma: no cover - exercised via tests with mocks
        return {"current record": f"unavailable ({exc})"}
    if not isinstance(record, dict):
        return {}
    return {k: v for k, v in record.items() if v not in ("", None)}
