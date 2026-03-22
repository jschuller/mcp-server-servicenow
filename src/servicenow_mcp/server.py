"""ServiceNow MCP Server — FastMCP singleton and service accessors."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastmcp import FastMCP
from fastmcp.server.middleware.response_limiting import ResponseLimitingMiddleware

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils.config import ServerConfig

if TYPE_CHECKING:
    import requests

logger = logging.getLogger(__name__)

_config: ServerConfig | None = None
_auth_manager: AuthManager | None = None

mcp = FastMCP("servicenow-mcp")
mcp.add_middleware(ResponseLimitingMiddleware(max_size=500_000))


def init_services(config: ServerConfig, *, require_auth_manager: bool = True) -> None:
    """Initialize the shared config and auth manager (call before importing tools).

    When OAuth proxy is active, the auth manager is not needed (per-user tokens
    are used instead), so ``require_auth_manager`` can be set to False.
    """
    global _config, _auth_manager
    _config = config
    if require_auth_manager:
        _auth_manager = AuthManager(config.auth, config.instance_url)
    logger.info(f"Services initialized for {config.instance_url}")


def get_config() -> ServerConfig:
    """Return the server config; raises if init_services() was not called."""
    if _config is None:
        raise RuntimeError("Call init_services() first")
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
    """
    from servicenow_mcp.utils.http import api_request

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


def get_sn_bearer_token() -> str | None:
    """Get the caller's SN bearer token if OAuth proxy is active.

    When the MCP server is running with ServiceNowProvider, each request
    carries a FastMCP JWT that wraps the user's upstream SN token.
    FastMCP's ``get_access_token()`` returns an ``AccessToken`` whose
    ``.token`` field is the original SN opaque token.

    Returns None when running in stdio mode or without OAuth proxy.
    """
    try:
        from fastmcp.server.dependencies import get_access_token

        access_token = get_access_token()
        return access_token.token if access_token else None
    except Exception:
        return None
