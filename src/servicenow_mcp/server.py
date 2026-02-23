"""ServiceNow MCP Server — FastMCP singleton and service accessors."""

import logging

from fastmcp import FastMCP

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils.config import ServerConfig

logger = logging.getLogger(__name__)

_config: ServerConfig | None = None
_auth_manager: AuthManager | None = None

mcp = FastMCP("servicenow-mcp")


def init_services(config: ServerConfig) -> None:
    """Initialize the shared config and auth manager (call before importing tools)."""
    global _config, _auth_manager
    _config = config
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
