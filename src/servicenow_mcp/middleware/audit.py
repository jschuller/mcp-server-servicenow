"""Audit middleware — one JSON line per tool call / resource read.

Lines go to ``stderr`` by default (``--audit-log stderr``), to a file
(``--audit-log /path/audit.jsonl``) or nowhere (``--audit-log off``). Never
stdout: on stdio transport that is the protocol channel. Values are never
logged — only ``data`` keys and a redacted, truncated query string.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastmcp.exceptions import NotFoundError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from mcp.types import TextContent

from servicenow_mcp.middleware.policy import SCHEMA_URI_RE, PolicyError, resolve_table
from servicenow_mcp.middleware.response_limit import TRUNCATED_META

AUDIT_LOGGER_NAME = "servicenow_mcp.audit"
TRUNCATION_SUFFIX = "\n\n[Response truncated due to size limit]"
RUN_ID = uuid.uuid4().hex
QUERY_MAX_CHARS = 200

logger = logging.getLogger(AUDIT_LOGGER_NAME)
logger.propagate = False

_enabled = False
_transport = "stdio"

_REDACT_RE = re.compile(
    r"(?i)((?:password|secret|token|api_key|apikey)[A-Za-z0-9_]*\s*"
    r"(?:!=|=|LIKE|STARTSWITH|ENDSWITH|IN))([^^]*)"
)


def configure_audit_log(setting: str, *, transport: str = "stdio") -> bool:
    """Install the audit handler. Returns True when auditing is active."""
    global _enabled, _transport
    _transport = transport
    for existing in list(logger.handlers):
        logger.removeHandler(existing)
        existing.close()
    logger.propagate = False

    target = (setting or "stderr").strip()
    if target.lower() == "off":
        _enabled = False
        return False

    handler: logging.Handler
    if target.lower() == "stderr":
        handler = logging.StreamHandler(sys.stderr)
    else:
        handler = logging.FileHandler(target, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    _enabled = True
    return True


def is_enabled() -> bool:
    return _enabled


def redact_query(query: str) -> str:
    """Mask values of password/secret/token-like fields and cap the length."""
    masked = _REDACT_RE.sub(r"\1[REDACTED]", query)
    if len(masked) > QUERY_MAX_CHARS:
        return masked[:QUERY_MAX_CHARS] + "…"
    return masked


def _current_config() -> Any:
    try:
        from servicenow_mcp.server import get_config_or_none
    except Exception:
        return None
    return get_config_or_none()


def _identity() -> Tuple[str, Optional[str]]:
    """Return (auth_mode, user) for the current request."""
    token = None
    try:
        from fastmcp.server.dependencies import get_access_token

        token = get_access_token()
    except Exception:
        token = None

    if token is not None:
        claims = getattr(token, "claims", None)
        claims = claims if isinstance(claims, dict) else {}
        client_id = getattr(token, "client_id", None)
        if claims.get("sn_auth") == "service-account":
            return "static-token", client_id
        user = claims.get("user_name") or claims.get("sub") or client_id
        return "oauth", user

    config = _current_config()
    if config is None:
        return "service-account", None
    auth = config.auth
    if auth.basic is not None and auth.basic.username:
        return "service-account", auth.basic.username
    if auth.oauth is not None:
        if auth.oauth.grant_type == "client_credentials":
            return "service-account", f"oauth-client:{auth.oauth.client_id}"
        return "service-account", auth.oauth.username
    if auth.api_key is not None:
        return "service-account", "api-key"
    return "service-account", None


async def _tool_tags(name: str) -> Optional[List[str]]:
    try:
        from servicenow_mcp.server import mcp

        tool = await mcp.get_tool(name)
    except Exception:
        return None
    tags = getattr(tool, "tags", None)
    return sorted(tags) if tags else None


def _classify_exception(exc: BaseException) -> Tuple[str, str]:
    message = f"{type(exc).__name__}: {str(exc)[:200]}"
    if isinstance(exc, PolicyError):
        return "denied", message
    if isinstance(exc, NotFoundError):
        return "unknown_tool", message
    return "error", message


def _is_truncated(result: Any) -> bool:
    if (getattr(result, "meta", None) or {}).get(TRUNCATED_META):
        return True  # a list cut to fit, structure kept
    content = getattr(result, "content", None) or []
    return any(
        isinstance(block, TextContent) and block.text.endswith(TRUNCATION_SUFFIX)
        for block in content
    )


def _emit(record: Dict[str, Any]) -> None:
    clean = {k: v for k, v in record.items() if v is not None}
    logger.info(json.dumps(clean, default=str, separators=(",", ":")))


def _base_record(event: str, name: str) -> Dict[str, Any]:
    auth_mode, user = _identity()
    return {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "run_id": RUN_ID,
        "event": event,
        "name": name,
        "user": user,
        "auth_mode": auth_mode,
        "transport": _transport,
    }


class AuditMiddleware(Middleware):
    """Emit one structured line per tool call and resource read."""

    async def on_call_tool(
        self, context: MiddlewareContext, call_next: CallNext
    ) -> Any:
        if not _enabled:
            return await call_next(context)

        name = context.message.name
        arguments: Dict[str, Any] = dict(context.message.arguments or {})
        record = _base_record("tool_call", name)
        record["table"] = resolve_table(name, arguments)
        sys_id = arguments.get("sys_id") or arguments.get("update_set_sys_id")
        record["sys_id"] = sys_id if isinstance(sys_id, str) else None
        query = arguments.get("query")
        record["query"] = redact_query(query) if isinstance(query, str) else None
        data = arguments.get("data")
        record["data_keys"] = sorted(data) if isinstance(data, dict) else None
        record["limit"] = arguments.get("limit")
        record["tags"] = await _tool_tags(name)
        start = time.perf_counter()
        try:
            result = await call_next(context)
        except BaseException as exc:
            record["outcome"], record["error"] = _classify_exception(exc)
            record["duration_ms"] = round((time.perf_counter() - start) * 1000, 1)
            _emit(record)
            raise
        else:
            record["outcome"] = "ok"
            if _is_truncated(result):
                record["truncated"] = True
            record["duration_ms"] = round((time.perf_counter() - start) * 1000, 1)
            _emit(record)
            return result

    async def on_read_resource(
        self, context: MiddlewareContext, call_next: CallNext
    ) -> Any:
        if not _enabled:
            return await call_next(context)

        uri = str(context.message.uri)
        record = _base_record("resource_read", uri)
        match = SCHEMA_URI_RE.match(uri)
        record["table"] = match.group("table") if match else None

        start = time.perf_counter()
        try:
            result = await call_next(context)
        except BaseException as exc:
            record["outcome"], record["error"] = _classify_exception(exc)
            if record["outcome"] == "unknown_tool":
                record["outcome"] = "unknown_resource"
            record["duration_ms"] = round((time.perf_counter() - start) * 1000, 1)
            _emit(record)
            raise
        record["outcome"] = "ok"
        record["duration_ms"] = round((time.perf_counter() - start) * 1000, 1)
        _emit(record)
        return result
