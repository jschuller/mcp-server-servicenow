"""Tests for ServiceNow token verifier."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from servicenow_mcp.auth.sn_token_verifier import ServiceNowTokenVerifier


INSTANCE_URL = "https://dev12345.service-now.com"


@pytest.fixture
def verifier() -> ServiceNowTokenVerifier:
    return ServiceNowTokenVerifier(instance_url=INSTANCE_URL, timeout_seconds=5)


def _make_mock_client(response: MagicMock | None = None, side_effect: Exception | None = None) -> MagicMock:
    """Create a properly structured mock for httpx.AsyncClient context manager."""
    mock_client = AsyncMock()
    if side_effect:
        mock_client.get.side_effect = side_effect
    else:
        mock_client.get.return_value = response

    # httpx.AsyncClient() returns an object; async with ... enters it
    mock_cls = MagicMock()
    mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_cls


class TestServiceNowTokenVerifier:
    @pytest.mark.asyncio
    async def test_valid_token_returns_access_token(self, verifier: ServiceNowTokenVerifier) -> None:
        """A 200 response from SN means the token is valid."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "result": {
                "user_name": "admin",
                "user_display_name": "System Administrator",
                "user_email": "admin@example.com",
                "user_sys_id": "6816f79cc0a8016401c5a33be04be441",
                "roles": "admin,itil",
            }
        }

        mock_cls = _make_mock_client(response=mock_response)

        with patch("servicenow_mcp.auth.sn_token_verifier.httpx.AsyncClient", mock_cls):
            result = await verifier.verify_token("valid-sn-token")

        assert result is not None
        assert result.token == "valid-sn-token"
        assert result.client_id == "admin"
        assert result.claims["user_name"] == "admin"
        assert result.claims["name"] == "System Administrator"
        assert result.claims["email"] == "admin@example.com"
        assert result.claims["sub"] == "6816f79cc0a8016401c5a33be04be441"

    @pytest.mark.asyncio
    async def test_401_response_returns_none(self, verifier: ServiceNowTokenVerifier) -> None:
        """A 401 from SN means the token is invalid/expired."""
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"

        mock_cls = _make_mock_client(response=mock_response)

        with patch("servicenow_mcp.auth.sn_token_verifier.httpx.AsyncClient", mock_cls):
            result = await verifier.verify_token("expired-token")

        assert result is None

    @pytest.mark.asyncio
    async def test_connection_error_returns_none(self, verifier: ServiceNowTokenVerifier) -> None:
        """Network errors should return None, not raise."""
        mock_cls = _make_mock_client(side_effect=httpx.ConnectError("Connection refused"))

        with patch("servicenow_mcp.auth.sn_token_verifier.httpx.AsyncClient", mock_cls):
            result = await verifier.verify_token("some-token")

        assert result is None

    @pytest.mark.asyncio
    async def test_timeout_returns_none(self, verifier: ServiceNowTokenVerifier) -> None:
        """Timeouts should return None, not raise."""
        mock_cls = _make_mock_client(side_effect=httpx.ReadTimeout("timed out"))

        with patch("servicenow_mcp.auth.sn_token_verifier.httpx.AsyncClient", mock_cls):
            result = await verifier.verify_token("some-token")

        assert result is None

    def test_instance_url_trailing_slash_stripped(self) -> None:
        """Trailing slashes on instance URL should be stripped."""
        v = ServiceNowTokenVerifier(instance_url="https://dev.service-now.com/")
        assert v.instance_url == "https://dev.service-now.com"
