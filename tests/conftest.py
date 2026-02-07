"""Shared test fixtures for the ServiceNow MCP server."""

import pytest

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils.config import (
    AuthConfig,
    AuthType,
    BasicAuthConfig,
    OAuthConfig,
    ServerConfig,
)


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
