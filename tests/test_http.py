"""Tests for HTTP request helper with mocked requests."""

import socket
from unittest.mock import MagicMock, patch

import pytest
import requests

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils.http import (
    ServiceNowAPIError,
    api_request,
    parse_json_response,
)


URL = "https://test.service-now.com/api/now/table/incident"


def _mock_response(
    status_code: int = 200,
    json_data: dict | None = None,
    text: str = "",
    content_type: str = "application/json",
    ok: bool | None = None,
    extra_headers: dict[str, str] | None = None,
) -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.ok = ok if ok is not None else (200 <= status_code < 300)
    resp.text = text or (str(json_data) if json_data else "")
    headers = {"Content-Type": content_type}
    if extra_headers:
        headers.update(extra_headers)
    resp.headers = headers
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = ValueError("No JSON")
    return resp


class TestApiRequest:
    """Tests for api_request function."""

    @patch("servicenow_mcp.utils.http.requests.request")
    def test_successful_request(
        self, mock_request: MagicMock, basic_auth_manager: AuthManager
    ) -> None:
        mock_request.return_value = _mock_response(200, {"result": []})
        response = api_request("GET", URL, basic_auth_manager)
        assert response.status_code == 200
        mock_request.assert_called_once()

    @patch("servicenow_mcp.utils.http.requests.request")
    def test_401_basic_auth_raises(
        self, mock_request: MagicMock, basic_auth_manager: AuthManager
    ) -> None:
        mock_request.return_value = _mock_response(401)
        with pytest.raises(ServiceNowAPIError, match="Authentication failed.*401"):
            api_request("GET", URL, basic_auth_manager)

    @patch("servicenow_mcp.utils.http.requests.request")
    def test_401_basic_auth_names_the_restriction(
        self, mock_request: MagicMock, basic_auth_manager: AuthManager
    ) -> None:
        """New instances refuse basic auth unless the user is web-service-only."""
        mock_request.return_value = _mock_response(401)
        with pytest.raises(ServiceNowAPIError) as exc:
            api_request("GET", URL, basic_auth_manager)
        message = str(exc.value)
        assert "Web service access only" in message
        assert "snc_basic_auth_api_access" in message
        assert "TROUBLESHOOTING.md#401-unauthorized" in message

    @patch("servicenow_mcp.utils.http.requests.request")
    def test_401_api_key_points_at_access_policies(
        self, mock_request: MagicMock
    ) -> None:
        from servicenow_mcp.utils.config import ApiKeyConfig, AuthConfig, AuthType

        manager = AuthManager(
            AuthConfig(type=AuthType.API_KEY, api_key=ApiKeyConfig(api_key="k")),
            "https://test.service-now.com",
        )
        mock_request.return_value = _mock_response(401)
        with pytest.raises(ServiceNowAPIError, match="REST API access policy.*GET"):
            api_request("GET", URL, manager)

    @patch("servicenow_mcp.utils.http.requests.request")
    def test_401_oauth_retries_on_success(
        self, mock_request: MagicMock, oauth_auth_manager: AuthManager
    ) -> None:
        """On 401 with OAuth, refresh token and retry. If retry succeeds, return response."""
        # Pre-set a token so get_headers() doesn't trigger _get_oauth_token
        oauth_auth_manager.token = "old-token"
        oauth_auth_manager.token_type = "Bearer"

        first_resp = _mock_response(401)
        second_resp = _mock_response(200, {"result": []})
        mock_request.side_effect = [first_resp, second_resp]

        with patch.object(oauth_auth_manager, "refresh_token") as mock_refresh:
            response = api_request("GET", URL, oauth_auth_manager)

        assert response.status_code == 200
        mock_refresh.assert_called_once()
        assert mock_request.call_count == 2

    @patch("servicenow_mcp.utils.http.requests.request")
    def test_401_oauth_retry_still_401(
        self, mock_request: MagicMock, oauth_auth_manager: AuthManager
    ) -> None:
        """If retry after refresh still returns 401, raise error."""
        oauth_auth_manager.token = "old-token"
        oauth_auth_manager.token_type = "Bearer"
        mock_request.return_value = _mock_response(401)

        with patch.object(oauth_auth_manager, "refresh_token"):
            with pytest.raises(ServiceNowAPIError, match="even after token refresh"):
                api_request("GET", URL, oauth_auth_manager)

    @patch("servicenow_mcp.utils.http.requests.request")
    def test_401_oauth_refresh_fails(
        self, mock_request: MagicMock, oauth_auth_manager: AuthManager
    ) -> None:
        """If token refresh itself fails, raise error."""
        oauth_auth_manager.token = "old-token"
        oauth_auth_manager.token_type = "Bearer"
        mock_request.return_value = _mock_response(401)

        with patch.object(
            oauth_auth_manager,
            "refresh_token",
            side_effect=ValueError("refresh failed"),
        ):
            with pytest.raises(ServiceNowAPIError, match="token refresh also failed"):
                api_request("GET", URL, oauth_auth_manager)

    @patch("servicenow_mcp.utils.http.requests.request")
    def test_403_raises(
        self, mock_request: MagicMock, basic_auth_manager: AuthManager
    ) -> None:
        mock_request.return_value = _mock_response(403)
        with pytest.raises(ServiceNowAPIError, match="Access denied.*403"):
            api_request("GET", URL, basic_auth_manager)

    @patch("servicenow_mcp.utils.http.requests.request")
    def test_403_links_the_roles_table(
        self, mock_request: MagicMock, basic_auth_manager: AuthManager
    ) -> None:
        mock_request.return_value = _mock_response(403)
        with pytest.raises(ServiceNowAPIError, match="docs/tools.md#roles"):
            api_request("GET", URL, basic_auth_manager)

    @patch("servicenow_mcp.utils.http.requests.request")
    def test_403_includes_response_body(
        self, mock_request: MagicMock, basic_auth_manager: AuthManager
    ) -> None:
        """403 error should include the response body for diagnosis (e.g. WebServicePolicyValidator)."""
        mock_request.return_value = _mock_response(
            403,
            text='{"error":{"message":"Access denied by WebServicePolicyValidator"}}',
        )
        with pytest.raises(ServiceNowAPIError, match="WebServicePolicyValidator"):
            api_request("GET", URL, basic_auth_manager)

    @patch("servicenow_mcp.utils.http.requests.request")
    def test_403_includes_diagnostic_headers(
        self, mock_request: MagicMock, basic_auth_manager: AuthManager
    ) -> None:
        """403 error should include diagnostic ServiceNow headers when present."""
        mock_request.return_value = _mock_response(
            403,
            text="Forbidden",
            extra_headers={
                "X-Is-Logged-In": "true",
                "X-Transaction-ID": "abc123def",
            },
        )
        with pytest.raises(ServiceNowAPIError, match="X-Transaction-ID.*abc123def"):
            api_request("GET", URL, basic_auth_manager)

    @patch("servicenow_mcp.utils.http.requests.request")
    def test_404_raises(
        self, mock_request: MagicMock, basic_auth_manager: AuthManager
    ) -> None:
        mock_request.return_value = _mock_response(404)
        with pytest.raises(ServiceNowAPIError, match="Not found.*404"):
            api_request("GET", URL, basic_auth_manager)

    @patch("servicenow_mcp.utils.http.requests.request")
    def test_404_includes_response_body(
        self, mock_request: MagicMock, basic_auth_manager: AuthManager
    ) -> None:
        """404 error should include the response body for diagnosis."""
        mock_request.return_value = _mock_response(
            404,
            text='{"error":{"message":"Table \'nonexistent\' not found"}}',
        )
        with pytest.raises(ServiceNowAPIError, match="Table.*nonexistent.*not found"):
            api_request("GET", URL, basic_auth_manager)

    @patch("servicenow_mcp.utils.http.requests.request")
    def test_500_raises_with_body(
        self, mock_request: MagicMock, basic_auth_manager: AuthManager
    ) -> None:
        mock_request.return_value = _mock_response(500, text="Internal Server Error")
        with pytest.raises(ServiceNowAPIError, match="HTTP 500"):
            api_request("GET", URL, basic_auth_manager)

    @patch("servicenow_mcp.utils.http.requests.request")
    def test_connection_error(
        self, mock_request: MagicMock, basic_auth_manager: AuthManager
    ) -> None:
        mock_request.side_effect = requests.ConnectionError("Connection refused")
        with pytest.raises(ServiceNowAPIError, match="Cannot connect"):
            api_request("GET", URL, basic_auth_manager)

    @patch("servicenow_mcp.utils.http.requests.request")
    def test_dns_failure_points_at_the_url(
        self, mock_request: MagicMock, basic_auth_manager: AuthManager
    ) -> None:
        """A typo'd or reclaimed instance fails DNS; say so instead of 'asleep'."""
        try:
            try:
                raise socket.gaierror(8, "nodename nor servname provided")
            except socket.gaierror as dns:
                raise OSError("Failed to resolve 'dev0.service-now.com'") from dns
        except OSError as reason:
            mock_request.side_effect = requests.ConnectionError(reason)
        with pytest.raises(ServiceNowAPIError, match="Cannot resolve the host"):
            api_request("GET", URL, basic_auth_manager)

    @patch("servicenow_mcp.utils.http.requests.request")
    def test_ssl_error_names_the_ca_bundle(
        self, mock_request: MagicMock, basic_auth_manager: AuthManager
    ) -> None:
        """SSLError subclasses ConnectionError; it must not read as 'asleep'."""
        mock_request.side_effect = requests.exceptions.SSLError(
            "certificate verify failed"
        )
        with pytest.raises(ServiceNowAPIError, match="REQUESTS_CA_BUNDLE"):
            api_request("GET", URL, basic_auth_manager)

    @patch("servicenow_mcp.utils.http.requests.request")
    def test_timeout_error(
        self, mock_request: MagicMock, basic_auth_manager: AuthManager
    ) -> None:
        mock_request.side_effect = requests.Timeout("timed out")
        with pytest.raises(ServiceNowAPIError, match="timed out"):
            api_request("GET", URL, basic_auth_manager)


class TestParseJsonResponse:
    """Tests for parse_json_response function."""

    def test_valid_json(self) -> None:
        resp = _mock_response(
            200, {"result": [{"sys_id": "abc"}]}, text='{"result": []}'
        )
        data = parse_json_response(resp, URL)
        assert "result" in data

    def test_empty_body(self) -> None:
        resp = _mock_response(200, text="")
        with pytest.raises(ServiceNowAPIError, match="Empty response body"):
            parse_json_response(resp, URL)

    def test_whitespace_only_body(self) -> None:
        resp = _mock_response(200, text="   \n  ")
        with pytest.raises(ServiceNowAPIError, match="Empty response body"):
            parse_json_response(resp, URL)

    def test_html_body(self) -> None:
        resp = _mock_response(
            200,
            text="<html><body>Login</body></html>",
            content_type="text/html",
        )
        with pytest.raises(ServiceNowAPIError, match="Got HTML instead of JSON"):
            parse_json_response(resp, URL)

    def test_html_body_gives_the_wake_url(self) -> None:
        resp = _mock_response(200, text="<html></html>", content_type="text/html")
        with pytest.raises(ServiceNowAPIError, match=r"dev\.do#!/home\?wu=true"):
            parse_json_response(resp, URL)

    def test_invalid_json(self) -> None:
        resp = _mock_response(200, text="not json at all")
        resp.json.side_effect = ValueError("Expecting value")
        with pytest.raises(ServiceNowAPIError, match="Invalid JSON"):
            parse_json_response(resp, URL)
