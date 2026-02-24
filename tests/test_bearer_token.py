"""Tests for bearer token support in HTTP client and server helper."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from servicenow_mcp.utils.http import ServiceNowAPIError, api_request


URL = "https://test.service-now.com/api/now/table/incident"


def _mock_response(
    status_code: int = 200,
    json_data: dict | None = None,
    text: str = "",
    content_type: str = "application/json",
    ok: bool | None = None,
) -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.ok = ok if ok is not None else (200 <= status_code < 300)
    resp.text = text or (str(json_data) if json_data else "")
    resp.headers = {"Content-Type": content_type}
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = ValueError("No JSON")
    return resp


class TestBearerTokenInApiRequest:
    """Tests for the bearer_token parameter in api_request."""

    @patch("servicenow_mcp.utils.http.requests.request")
    def test_bearer_token_sets_auth_header(self, mock_request: MagicMock) -> None:
        """When bearer_token is provided, Authorization header should be Bearer."""
        mock_request.return_value = _mock_response(200, {"result": []})

        api_request("GET", URL, bearer_token="my-sn-token")

        call_kwargs = mock_request.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
        assert headers["Authorization"] == "Bearer my-sn-token"
        assert headers["Accept"] == "application/json"

    @patch("servicenow_mcp.utils.http.requests.request")
    def test_bearer_token_401_raises_immediately(self, mock_request: MagicMock) -> None:
        """With bearer_token, a 401 should raise immediately (no retry)."""
        mock_request.return_value = _mock_response(401)

        with pytest.raises(ServiceNowAPIError, match="per-user OAuth token"):
            api_request("GET", URL, bearer_token="expired-token")

        # Should only be called once (no retry)
        assert mock_request.call_count == 1

    @patch("servicenow_mcp.utils.http.requests.request")
    def test_bearer_token_with_params(self, mock_request: MagicMock) -> None:
        """bearer_token should work alongside params and json_data."""
        mock_request.return_value = _mock_response(200, {"result": []})

        api_request(
            "POST", URL,
            bearer_token="my-token",
            params={"sysparm_limit": 10},
            json_data={"short_description": "test"},
        )

        call_kwargs = mock_request.call_args
        assert call_kwargs.kwargs["params"] == {"sysparm_limit": 10}
        assert call_kwargs.kwargs["json"] == {"short_description": "test"}

    def test_no_auth_raises_error(self) -> None:
        """If neither auth_manager nor bearer_token is provided, raise."""
        with pytest.raises(ServiceNowAPIError, match="Either auth_manager or bearer_token"):
            api_request("GET", URL)


class TestGetSnBearerToken:
    """Tests for get_sn_bearer_token() helper."""

    def test_returns_none_when_no_auth_context(self) -> None:
        """Outside of an OAuth proxy context, should return None."""
        from servicenow_mcp.server import get_sn_bearer_token

        result = get_sn_bearer_token()
        assert result is None

    def test_returns_token_when_access_token_present(self) -> None:
        """When FastMCP auth context has an access token, return the raw token."""
        from servicenow_mcp.server import get_sn_bearer_token

        mock_token = MagicMock()
        mock_token.token = "sn-user-oauth-token"

        with patch(
            "fastmcp.server.dependencies.get_access_token",
            return_value=mock_token,
        ):
            result = get_sn_bearer_token()
            assert result == "sn-user-oauth-token"

    def test_returns_none_when_access_token_is_none(self) -> None:
        """When get_access_token returns None, should return None."""
        from servicenow_mcp.server import get_sn_bearer_token

        with patch(
            "fastmcp.server.dependencies.get_access_token",
            return_value=None,
        ):
            result = get_sn_bearer_token()
            assert result is None

    def test_returns_none_on_exception(self) -> None:
        """If get_access_token raises, return None (don't crash)."""
        from servicenow_mcp.server import get_sn_bearer_token

        with patch(
            "fastmcp.server.dependencies.get_access_token",
            side_effect=RuntimeError("no context"),
        ):
            result = get_sn_bearer_token()
            assert result is None
