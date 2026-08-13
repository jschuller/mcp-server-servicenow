"""Tests for AuthManager OAuth token handling (timeout, refresh grant)."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils.config import AuthConfig, ServerConfig


TOKEN_URL = "https://test.service-now.com/oauth_token.do"


def _token_response(
    status_code: int = 200,
    access_token: str = "access-1",
    refresh_token: str | None = "refresh-1",
) -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    data = {"access_token": access_token, "token_type": "Bearer"}
    if refresh_token is not None:
        data["refresh_token"] = refresh_token
    resp.json.return_value = data
    resp.text = str(data)
    return resp


class TestPasswordGrant:
    """Tests for the initial password grant in _get_oauth_token."""

    @patch("servicenow_mcp.auth.auth_manager.requests.post")
    def test_sends_timeout_and_password_grant(
        self, mock_post: MagicMock, oauth_auth_manager: AuthManager
    ) -> None:
        mock_post.return_value = _token_response()
        headers = oauth_auth_manager.get_headers()

        assert headers["Authorization"] == "Bearer access-1"
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == TOKEN_URL
        assert kwargs["timeout"] == 30
        assert kwargs["data"]["grant_type"] == "password"

    @patch("servicenow_mcp.auth.auth_manager.requests.post")
    def test_custom_timeout_honored(
        self, mock_post: MagicMock, oauth_auth_config: AuthConfig
    ) -> None:
        manager = AuthManager(
            oauth_auth_config, "https://test.service-now.com", timeout=7
        )
        mock_post.return_value = _token_response()
        manager.get_headers()
        assert mock_post.call_args.kwargs["timeout"] == 7

    @patch("servicenow_mcp.auth.auth_manager.requests.post")
    def test_stores_refresh_token(
        self, mock_post: MagicMock, oauth_auth_manager: AuthManager
    ) -> None:
        mock_post.return_value = _token_response(refresh_token="refresh-1")
        oauth_auth_manager.get_headers()
        assert oauth_auth_manager._refresh_token == "refresh-1"

    @patch("servicenow_mcp.auth.auth_manager.requests.post")
    def test_failure_raises(
        self, mock_post: MagicMock, oauth_auth_manager: AuthManager
    ) -> None:
        resp = MagicMock(spec=requests.Response)
        resp.status_code = 401
        resp.text = "access_denied"
        mock_post.return_value = resp
        with pytest.raises(ValueError, match="Failed to get OAuth token: 401"):
            oauth_auth_manager.get_headers()


class TestRefreshToken:
    """Tests for refresh_token() grant selection and fallback."""

    def _seed(self, manager: AuthManager, refresh_token: str = "refresh-1") -> None:
        """Put the manager in a post-password-grant state."""
        manager.token = "access-1"
        manager.token_type = "Bearer"
        manager._refresh_token = refresh_token

    @patch("servicenow_mcp.auth.auth_manager.requests.post")
    def test_uses_refresh_grant_when_token_held(
        self, mock_post: MagicMock, oauth_auth_manager: AuthManager
    ) -> None:
        self._seed(oauth_auth_manager)
        mock_post.return_value = _token_response(
            access_token="access-2", refresh_token="refresh-2"
        )
        oauth_auth_manager.refresh_token()

        mock_post.assert_called_once()
        kwargs = mock_post.call_args.kwargs
        assert kwargs["data"] == {
            "grant_type": "refresh_token",
            "refresh_token": "refresh-1",
        }
        assert kwargs["timeout"] == 30
        assert oauth_auth_manager.token == "access-2"
        assert oauth_auth_manager._refresh_token == "refresh-2"

    @patch("servicenow_mcp.auth.auth_manager.requests.post")
    def test_keeps_refresh_token_when_not_rotated(
        self, mock_post: MagicMock, oauth_auth_manager: AuthManager
    ) -> None:
        self._seed(oauth_auth_manager)
        mock_post.return_value = _token_response(
            access_token="access-2", refresh_token=None
        )
        oauth_auth_manager.refresh_token()
        assert oauth_auth_manager._refresh_token == "refresh-1"

    @patch("servicenow_mcp.auth.auth_manager.requests.post")
    def test_falls_back_to_password_grant_on_http_error(
        self, mock_post: MagicMock, oauth_auth_manager: AuthManager
    ) -> None:
        self._seed(oauth_auth_manager)
        rejected = MagicMock(spec=requests.Response)
        rejected.status_code = 401
        rejected.text = "invalid_grant"
        mock_post.side_effect = [
            rejected,
            _token_response(access_token="access-3", refresh_token="refresh-3"),
        ]
        oauth_auth_manager.refresh_token()

        assert mock_post.call_count == 2
        first, second = mock_post.call_args_list
        assert first.kwargs["data"]["grant_type"] == "refresh_token"
        assert second.kwargs["data"]["grant_type"] == "password"
        assert oauth_auth_manager.token == "access-3"
        assert oauth_auth_manager._refresh_token == "refresh-3"

    @patch("servicenow_mcp.auth.auth_manager.requests.post")
    def test_falls_back_to_password_grant_on_connection_error(
        self, mock_post: MagicMock, oauth_auth_manager: AuthManager
    ) -> None:
        self._seed(oauth_auth_manager)
        mock_post.side_effect = [
            requests.ConnectionError("Connection refused"),
            _token_response(access_token="access-3"),
        ]
        oauth_auth_manager.refresh_token()

        assert mock_post.call_count == 2
        assert mock_post.call_args_list[1].kwargs["data"]["grant_type"] == "password"
        assert oauth_auth_manager.token == "access-3"

    @patch("servicenow_mcp.auth.auth_manager.requests.post")
    def test_password_grant_when_no_refresh_token_held(
        self, mock_post: MagicMock, oauth_auth_manager: AuthManager
    ) -> None:
        mock_post.return_value = _token_response()
        oauth_auth_manager.refresh_token()
        mock_post.assert_called_once()
        assert mock_post.call_args.kwargs["data"]["grant_type"] == "password"

    @patch("servicenow_mcp.auth.auth_manager.requests.post")
    def test_noop_for_basic_auth(
        self, mock_post: MagicMock, basic_auth_manager: AuthManager
    ) -> None:
        basic_auth_manager.refresh_token()
        mock_post.assert_not_called()


class TestServerWiring:
    """init_services must thread ServerConfig.timeout into the AuthManager."""

    def test_init_services_passes_timeout(self, oauth_auth_config: AuthConfig) -> None:
        from servicenow_mcp import server

        config = ServerConfig(
            instance_url="https://test.service-now.com",
            auth=oauth_auth_config,
            timeout=12,
        )
        saved_config, saved_manager = server._config, server._auth_manager
        try:
            server.init_services(config)
            assert server._auth_manager is not None
            assert server._auth_manager.timeout == 12
        finally:
            server._config, server._auth_manager = saved_config, saved_manager
