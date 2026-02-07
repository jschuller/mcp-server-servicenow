"""Tests for Pydantic config models."""

import pytest
from pydantic import ValidationError

from servicenow_mcp.utils.config import (
    ApiKeyConfig,
    AuthConfig,
    AuthType,
    BasicAuthConfig,
    OAuthConfig,
    ServerConfig,
)


class TestAuthType:
    def test_basic_value(self) -> None:
        assert AuthType.BASIC.value == "basic"

    def test_oauth_value(self) -> None:
        assert AuthType.OAUTH.value == "oauth"

    def test_api_key_value(self) -> None:
        assert AuthType.API_KEY.value == "api_key"


class TestBasicAuthConfig:
    def test_valid(self) -> None:
        config = BasicAuthConfig(username="admin", password="pass123")
        assert config.username == "admin"
        assert config.password == "pass123"

    def test_missing_username(self) -> None:
        with pytest.raises(ValidationError):
            BasicAuthConfig(password="pass123")  # type: ignore[call-arg]

    def test_missing_password(self) -> None:
        with pytest.raises(ValidationError):
            BasicAuthConfig(username="admin")  # type: ignore[call-arg]


class TestOAuthConfig:
    def test_valid_minimal(self) -> None:
        config = OAuthConfig(
            client_id="cid",
            client_secret="csecret",
            username="admin",
            password="pass",
        )
        assert config.client_id == "cid"
        assert config.token_url is None

    def test_valid_with_token_url(self) -> None:
        config = OAuthConfig(
            client_id="cid",
            client_secret="csecret",
            username="admin",
            password="pass",
            token_url="https://test.service-now.com/oauth_token.do",
        )
        assert config.token_url == "https://test.service-now.com/oauth_token.do"

    def test_missing_client_id(self) -> None:
        with pytest.raises(ValidationError):
            OAuthConfig(
                client_secret="csecret",
                username="admin",
                password="pass",
            )  # type: ignore[call-arg]


class TestApiKeyConfig:
    def test_valid(self) -> None:
        config = ApiKeyConfig(api_key="my-key")
        assert config.api_key == "my-key"
        assert config.header_name == "X-ServiceNow-API-Key"

    def test_custom_header(self) -> None:
        config = ApiKeyConfig(api_key="my-key", header_name="X-Custom")
        assert config.header_name == "X-Custom"

    def test_missing_api_key(self) -> None:
        with pytest.raises(ValidationError):
            ApiKeyConfig()  # type: ignore[call-arg]


class TestAuthConfig:
    def test_basic_type(self) -> None:
        config = AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="admin", password="pass"),
        )
        assert config.type == AuthType.BASIC
        assert config.basic is not None
        assert config.oauth is None

    def test_oauth_type(self) -> None:
        config = AuthConfig(
            type=AuthType.OAUTH,
            oauth=OAuthConfig(
                client_id="cid",
                client_secret="csecret",
                username="admin",
                password="pass",
            ),
        )
        assert config.type == AuthType.OAUTH
        assert config.oauth is not None

    def test_api_key_type(self) -> None:
        config = AuthConfig(
            type=AuthType.API_KEY,
            api_key=ApiKeyConfig(api_key="my-key"),
        )
        assert config.type == AuthType.API_KEY
        assert config.api_key is not None

    def test_missing_type(self) -> None:
        with pytest.raises(ValidationError):
            AuthConfig()  # type: ignore[call-arg]


class TestServerConfig:
    def test_valid_minimal(self, basic_auth_config: AuthConfig) -> None:
        config = ServerConfig(
            instance_url="https://test.service-now.com",
            auth=basic_auth_config,
        )
        assert config.instance_url == "https://test.service-now.com"
        assert config.debug is False
        assert config.timeout == 30

    def test_custom_timeout(self, basic_auth_config: AuthConfig) -> None:
        config = ServerConfig(
            instance_url="https://test.service-now.com",
            auth=basic_auth_config,
            timeout=60,
        )
        assert config.timeout == 60

    def test_api_url_property(self, basic_auth_config: AuthConfig) -> None:
        config = ServerConfig(
            instance_url="https://test.service-now.com",
            auth=basic_auth_config,
        )
        assert config.api_url == "https://test.service-now.com/api/now"

    def test_missing_instance_url(self, basic_auth_config: AuthConfig) -> None:
        with pytest.raises(ValidationError):
            ServerConfig(auth=basic_auth_config)  # type: ignore[call-arg]

    def test_missing_auth(self) -> None:
        with pytest.raises(ValidationError):
            ServerConfig(instance_url="https://test.service-now.com")  # type: ignore[call-arg]
