"""Shared test fixtures for the ServiceNow MCP server."""

from typing import Any
from unittest.mock import Mock

import pytest

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils.config import (
    AuthConfig,
    AuthType,
    BasicAuthConfig,
    OAuthConfig,
    ServerConfig,
)


@pytest.fixture(autouse=True)
def pristine_mcp():
    """Undo per-test mutations of the module-level FastMCP singleton.

    ``mcp.disable()`` appends a visibility transform, ``cli.main()`` assigns
    ``mcp.auth`` and installs the audit handler, and ``add_middleware`` would
    stack — snapshot and restore all of them so test files stay independent.
    """
    from servicenow_mcp.middleware.audit import configure_audit_log
    from servicenow_mcp.server import mcp

    transforms = list(getattr(mcp, "_transforms", []))
    middleware = list(mcp.middleware)
    auth = mcp.auth
    yield
    if hasattr(mcp, "_transforms"):
        mcp._transforms[:] = transforms
    mcp.middleware[:] = middleware
    mcp.auth = auth
    configure_audit_log("off")


def make_server_config(**overrides: Any) -> ServerConfig:
    """A basic-auth ServerConfig pointing at the test instance, with overrides."""
    base: dict[str, Any] = {
        "instance_url": "https://test.service-now.com",
        "auth": AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="admin", password="test123"),
        ),
    }
    base.update(overrides)
    return ServerConfig(**base)


def init_test_services(**overrides: Any) -> ServerConfig:
    """init_services() with a test config and register every tool + resource."""
    from servicenow_mcp.server import init_services

    config = make_server_config(**overrides)
    init_services(config)

    import servicenow_mcp.resources  # noqa: F401
    import servicenow_mcp.tools.cmdb_tools  # noqa: F401
    import servicenow_mcp.tools.system_tools  # noqa: F401
    import servicenow_mcp.tools.table_tools  # noqa: F401
    import servicenow_mcp.tools.update_set_tools  # noqa: F401

    return config


def sn_response(payload: Any) -> Mock:
    """A requests.Response stand-in that parse_json_response() accepts."""
    import json

    response = Mock()
    response.status_code = 200
    response.ok = True
    response.text = json.dumps(payload)
    response.headers = {"Content-Type": "application/json"}
    response.json.return_value = payload
    return response


@pytest.fixture
def basic_auth_config() -> AuthConfig:
    return AuthConfig(
        type=AuthType.BASIC,
        basic=BasicAuthConfig(username="admin", password="test123"),
    )


@pytest.fixture
def oauth_auth_config() -> AuthConfig:
    return AuthConfig(
        type=AuthType.OAUTH,
        oauth=OAuthConfig(
            client_id="test-client-id",
            client_secret="test-client-secret",
            username="admin",
            password="test123",
        ),
    )


@pytest.fixture
def server_config(basic_auth_config: AuthConfig) -> ServerConfig:
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=basic_auth_config,
    )


@pytest.fixture
def oauth_server_config(oauth_auth_config: AuthConfig) -> ServerConfig:
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=oauth_auth_config,
    )


@pytest.fixture
def basic_auth_manager(basic_auth_config: AuthConfig) -> AuthManager:
    return AuthManager(basic_auth_config, "https://test.service-now.com")


@pytest.fixture
def oauth_auth_manager(oauth_auth_config: AuthConfig) -> AuthManager:
    return AuthManager(oauth_auth_config, "https://test.service-now.com")
