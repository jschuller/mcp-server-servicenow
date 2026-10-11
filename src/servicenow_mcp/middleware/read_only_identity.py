"""Hide write tools from a caller whose ServiceNow identity has ``snc_read_only``.

``snc_read_only`` makes ServiceNow refuse every write by that user, admin
included, so listing write tools only invites calls that will fail. This
middleware drops tools tagged ``write`` from ``tools/list`` and refuses a call
to one with a ``PolicyError``.

It is a usability measure, not a security control: ServiceNow's ACLs and
``snc_read_only`` remain the boundary, and ``--read-only`` stays the only
server-side guarantee. It **fails open** — when the role lookup fails or times
out (a sleeping PDI, an identity that cannot read its own role rows) the write
tools stay visible and ServiceNow refuses the write.

Where the answer comes from:
- the configured service account (stdio, or HTTP with static tokens): one
  ``has_role`` lookup on the first ``tools/list`` or write call; only a
  definite answer is cached, for the life of the config;
- the OAuth proxy: the ``sn_read_only`` claim that ``ServiceNowTokenVerifier``
  sets per token (cached with the token).

FastMCP's own component authorization (``AuthMiddleware``, ``require_roles``)
is skipped on stdio, which is why this is a middleware of our own.
"""

from __future__ import annotations

import logging
from functools import partial
from typing import Any, Optional, Sequence, Tuple

import anyio
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

from servicenow_mcp.middleware.policy import PolicyError
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.user import has_role

logger = logging.getLogger(__name__)

READ_ONLY_ROLE = "snc_read_only"
READ_ONLY_CLAIM = "sn_read_only"
LOOKUP_TIMEOUT_SECONDS = 5
WRITE_TAG = "write"


def _current_config() -> Optional[ServerConfig]:
    try:
        from servicenow_mcp.server import get_config_or_none
    except Exception:
        return None
    return get_config_or_none()


def _caller_claims() -> Optional[dict[str, Any]]:
    """Claims of a per-user OAuth token, or None for the service account."""
    try:
        from fastmcp.server.dependencies import get_access_token

        token = get_access_token()
    except Exception:
        return None
    if token is None:
        return None
    claims = getattr(token, "claims", None)
    if not isinstance(claims, dict) or claims.get("sn_auth") == "service-account":
        return None
    return claims


def _is_write(tool: Any) -> bool:
    return WRITE_TAG in (getattr(tool, "tags", None) or ())


class ReadOnlyIdentityMiddleware(Middleware):
    """Drop and refuse write tools when the caller holds ``snc_read_only``."""

    def __init__(self) -> None:
        # (config the answer belongs to, answer) — a new config starts over.
        self._service_account: Tuple[Optional[ServerConfig], Optional[bool]] = (
            None,
            None,
        )

    async def _caller_is_read_only(self, config: ServerConfig) -> bool:
        claims = _caller_claims()
        if claims is not None:
            return claims.get(READ_ONLY_CLAIM) is True

        cached_for, answer = self._service_account
        if cached_for is config and answer is not None:
            return answer
        answer = await anyio.to_thread.run_sync(
            partial(
                has_role,
                config.api_url,
                min(config.timeout, LOOKUP_TIMEOUT_SECONDS),
                READ_ONLY_ROLE,
            )
        )
        if answer is None:
            logger.info("Role lookup failed; write tools stay listed")
            return False
        self._service_account = (config, answer)
        if answer:
            logger.info("Identity has %s: write tools hidden", READ_ONLY_ROLE)
        return answer

    async def _should_hide(self) -> bool:
        config = _current_config()
        # --read-only already hides the write tools; no lookup needed.
        if config is None or config.read_only:
            return False
        return await self._caller_is_read_only(config)

    async def on_list_tools(
        self, context: MiddlewareContext, call_next: CallNext
    ) -> Sequence[Any]:
        tools = await call_next(context)
        if not any(_is_write(tool) for tool in tools):
            return tools
        if not await self._should_hide():
            return tools
        return [tool for tool in tools if not _is_write(tool)]

    async def on_call_tool(
        self, context: MiddlewareContext, call_next: CallNext
    ) -> Any:
        if await self._is_write_tool(context.message.name) and (
            await self._should_hide()
        ):
            raise PolicyError(
                f"identity has {READ_ONLY_ROLE}; write tools are hidden "
                f"({context.message.name} would be refused by ServiceNow)"
            )
        return await call_next(context)

    @staticmethod
    async def _is_write_tool(name: str) -> bool:
        try:
            from servicenow_mcp.server import mcp

            tool = await mcp.get_tool(name)
        except Exception:
            return False
        return _is_write(tool)
