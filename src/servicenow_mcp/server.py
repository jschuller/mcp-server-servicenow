"""ServiceNow MCP Server — FastMCP singleton and service accessors."""

from __future__ import annotations

import functools
import logging
from typing import TYPE_CHECKING

import anyio
from fastmcp import FastMCP
from fastmcp.server.middleware.response_limiting import ResponseLimitingMiddleware

from servicenow_mcp import __version__
from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.middleware.audit import TRUNCATION_SUFFIX, AuditMiddleware
from servicenow_mcp.middleware.policy import PolicyMiddleware
from servicenow_mcp.utils.config import ServerConfig

if TYPE_CHECKING:
    import requests

logger = logging.getLogger(__name__)

_config: ServerConfig | None = None
_auth_manager: AuthManager | None = None

mcp = FastMCP("servicenow-mcp", version=__version__)
# The first middleware added is the outermost. Audit wraps everything so policy
# denials and truncated responses are recorded; policy runs before the tool;
# the response limiter stays innermost. Both of ours read the config lazily per
# call and no-op until init_services() has run.
mcp.add_middleware(AuditMiddleware())
mcp.add_middleware(PolicyMiddleware())
mcp.add_middleware(
    ResponseLimitingMiddleware(max_size=500_000, truncation_suffix=TRUNCATION_SUFFIX)
)


def init_services(config: ServerConfig, *, require_auth_manager: bool = True) -> None:
    """Initialize the shared config and auth manager (call before importing tools).

    When OAuth proxy is active, the auth manager is not needed (per-user tokens
    are used instead), so ``require_auth_manager`` can be set to False.
    """
    global _config, _auth_manager
    _config = config
    if require_auth_manager:
        _auth_manager = AuthManager(
            config.auth, config.instance_url, timeout=config.timeout
        )
    logger.info(f"Services initialized for {config.instance_url}")


def get_config() -> ServerConfig:
    """Return the server config; raises if init_services() was not called."""
    if _config is None:
        raise RuntimeError("Call init_services() first")
    return _config


def get_config_or_none() -> ServerConfig | None:
    """Return the server config, or None before init_services() (used by middleware)."""
    return _config


def get_auth_manager() -> AuthManager:
    """Return the auth manager; raises if init_services() was not called."""
    if _auth_manager is None:
        raise RuntimeError("Call init_services() first")
    return _auth_manager


def make_sn_request(
    method: str,
    url: str,
    timeout: int = 30,
    params: dict | None = None,
    json_data: dict | None = None,
) -> "requests.Response":
    """Make a ServiceNow API request, automatically using per-user OAuth token if available.

    When the OAuth proxy is active, uses the caller's SN bearer token.
    Otherwise falls back to the global auth manager.

    In read-only mode (``--read-only``) any non-GET request is refused here as
    well, so a future tool that forgets its ``write`` tag cannot mutate data.
    """
    from servicenow_mcp.utils.http import ServiceNowAPIError, api_request

    if _config is not None and _config.read_only and method.upper() != "GET":
        raise ServiceNowAPIError(
            f"Server is in read-only mode (--read-only); refusing {method.upper()} {url}"
        )

    bearer = get_sn_bearer_token()
    if bearer:
        return api_request(
            method,
            url,
            timeout=timeout,
            params=params,
            json_data=json_data,
            bearer_token=bearer,
        )
    return api_request(
        method, url, get_auth_manager(), timeout, params=params, json_data=json_data
    )


async def make_sn_request_async(
    method: str,
    url: str,
    timeout: int = 30,
    params: dict | None = None,
    json_data: dict | None = None,
) -> "requests.Response":
    """Run :func:`make_sn_request` on a worker thread.

    Async tools execute inline on the event loop, so a blocking ``requests``
    call inside one would stall every session on streamable-http. Context
    variables are copied to the thread, so the per-user bearer token still
    resolves.
    """
    return await anyio.to_thread.run_sync(
        functools.partial(
            make_sn_request, method, url, timeout, params=params, json_data=json_data
        )
    )


def get_sn_bearer_token() -> str | None:
    """Get the caller's SN bearer token if OAuth proxy is active.

    When the MCP server is running with ServiceNowProvider, each request
    carries a FastMCP JWT that wraps the user's upstream SN token.
    FastMCP's ``get_access_token()`` returns an ``AccessToken`` whose
    ``.token`` field is the original SN opaque token.

    Static MCP tokens (``MCP_STATIC_TOKENS``) are tagged ``sn_auth:
    service-account`` by the CLI; they are *not* ServiceNow credentials, so
    this returns None for them and the request falls back to the configured
    service account.

    Returns None when running in stdio mode or without OAuth proxy.
    """
    try:
        from fastmcp.server.dependencies import get_access_token

        access_token = get_access_token()
        if access_token is None:
            return None
        claims = getattr(access_token, "claims", None)
        if isinstance(claims, dict) and claims.get("sn_auth") == "service-account":
            return None
        return access_token.token
    except Exception:
        return None
