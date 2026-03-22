"""Tests for ServiceNow token verifier."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from servicenow_mcp.auth.sn_token_verifier import ServiceNowTokenVerifier


INSTANCE_URL = "https://dev12345.service-now.com"


@pytest.fixture
def verifier() -> ServiceNowTokenVerifier:
    return ServiceNowTokenVerifier(instance_url=INSTANCE_URL, timeout_seconds=5)


def _make_mock_client(
    response: MagicMock | None = None, side_effect: Exception | None = None
) -> MagicMock:
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
    async def test_valid_token_returns_access_token(
        self, verifier: ServiceNowTokenVerifier
    ) -> None:
        """A 200 response from SN Table API means the token is valid."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "result": [
                {
                    "user_name": "admin",
                    "name": "System Administrator",
                    "email": "admin@example.com",
                    "sys_id": "6816f79cc0a8016401c5a33be04be441",
                    "roles": "admin,itil",
                }
            ]
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
    async def test_valid_token_empty_results_returns_none(
        self, verifier: ServiceNowTokenVerifier
    ) -> None:
        """A 200 with empty result list means no user found."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": []}

        mock_cls = _make_mock_client(response=mock_response)

        with patch("servicenow_mcp.auth.sn_token_verifier.httpx.AsyncClient", mock_cls):
            result = await verifier.verify_token("valid-but-no-user")

        assert result is None

    @pytest.mark.asyncio
    async def test_401_response_returns_none(
        self, verifier: ServiceNowTokenVerifier
    ) -> None:
        """A 401 from SN means the token is invalid/expired."""
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"

        mock_cls = _make_mock_client(response=mock_response)

        with patch("servicenow_mcp.auth.sn_token_verifier.httpx.AsyncClient", mock_cls):
            result = await verifier.verify_token("expired-token")

        assert result is None

    @pytest.mark.asyncio
    async def test_connection_error_returns_none(
        self, verifier: ServiceNowTokenVerifier
    ) -> None:
        """Network errors should return None, not raise."""
        mock_cls = _make_mock_client(
            side_effect=httpx.ConnectError("Connection refused")
        )

        with patch("servicenow_mcp.auth.sn_token_verifier.httpx.AsyncClient", mock_cls):
            result = await verifier.verify_token("some-token")

        assert result is None

    @pytest.mark.asyncio
    async def test_timeout_returns_none(
        self, verifier: ServiceNowTokenVerifier
    ) -> None:
        """Timeouts should return None, not raise."""
        mock_cls = _make_mock_client(side_effect=httpx.ReadTimeout("timed out"))

        with patch("servicenow_mcp.auth.sn_token_verifier.httpx.AsyncClient", mock_cls):
            result = await verifier.verify_token("some-token")

        assert result is None

    def test_instance_url_trailing_slash_stripped(self) -> None:
        """Trailing slashes on instance URL should be stripped."""
        v = ServiceNowTokenVerifier(instance_url="https://dev.service-now.com/")
        assert v.instance_url == "https://dev.service-now.com"


def _valid_sn_response() -> MagicMock:
    """Create a mock 200 response with a valid SN user."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "result": [
            {
                "user_name": "admin",
                "name": "System Administrator",
                "email": "admin@example.com",
                "sys_id": "abc123",
                "roles": "admin",
            }
        ]
    }
    return resp


class TestTokenVerificationCache:
    @pytest.mark.asyncio
    async def test_cache_hit_skips_api_call(self) -> None:
        """Second call with same token should use cache, not call SN API."""
        verifier = ServiceNowTokenVerifier(
            instance_url=INSTANCE_URL,
            cache_ttl_seconds=300,
        )
        mock_cls = _make_mock_client(response=_valid_sn_response())

        with patch("servicenow_mcp.auth.sn_token_verifier.httpx.AsyncClient", mock_cls):
            first = await verifier.verify_token("cached-token")
            second = await verifier.verify_token("cached-token")

        assert first is not None
        assert second is not None
        assert second.token == "cached-token"
        # AsyncClient context manager entered only once (cache hit on second call)
        assert mock_cls.return_value.__aenter__.await_count == 1

    @pytest.mark.asyncio
    async def test_cache_disabled(self) -> None:
        """With cache_ttl_seconds=None, every call hits the API."""
        verifier = ServiceNowTokenVerifier(
            instance_url=INSTANCE_URL,
            cache_ttl_seconds=None,
        )
        mock_cls = _make_mock_client(response=_valid_sn_response())

        with patch("servicenow_mcp.auth.sn_token_verifier.httpx.AsyncClient", mock_cls):
            await verifier.verify_token("token-a")
            await verifier.verify_token("token-a")

        assert mock_cls.return_value.__aenter__.await_count == 2

    @pytest.mark.asyncio
    async def test_cache_expiry(self) -> None:
        """Expired cache entries should trigger a fresh API call."""
        verifier = ServiceNowTokenVerifier(
            instance_url=INSTANCE_URL,
            cache_ttl_seconds=1,
        )
        mock_cls = _make_mock_client(response=_valid_sn_response())

        with patch("servicenow_mcp.auth.sn_token_verifier.httpx.AsyncClient", mock_cls):
            await verifier.verify_token("expiry-token")
            # Manually expire the cache entry
            for entry in verifier._cache.values():
                entry.expires_at = 0
            await verifier.verify_token("expiry-token")

        # Two API calls: first miss + expired entry
        assert mock_cls.return_value.__aenter__.await_count == 2

    @pytest.mark.asyncio
    async def test_cache_eviction_on_size_limit(self) -> None:
        """Cache should evict expired entries when hitting max size."""
        verifier = ServiceNowTokenVerifier(
            instance_url=INSTANCE_URL,
            cache_ttl_seconds=300,
            max_cache_size=2,
        )
        mock_cls = _make_mock_client(response=_valid_sn_response())

        with patch("servicenow_mcp.auth.sn_token_verifier.httpx.AsyncClient", mock_cls):
            await verifier.verify_token("token-1")
            await verifier.verify_token("token-2")
            # Expire all entries so eviction can reclaim space
            for entry in verifier._cache.values():
                entry.expires_at = 0
            await verifier.verify_token("token-3")

        # token-3 should be cached, expired entries evicted
        assert len(verifier._cache) == 1


class TestConnectionPooling:
    @pytest.mark.asyncio
    async def test_shared_http_client_used(self) -> None:
        """When http_client is provided, it should be used instead of creating a new one."""
        mock_client = AsyncMock()
        mock_client.get.return_value = _valid_sn_response()

        verifier = ServiceNowTokenVerifier(
            instance_url=INSTANCE_URL,
            http_client=mock_client,
            cache_ttl_seconds=None,
        )

        result = await verifier.verify_token("pooled-token")

        assert result is not None
        assert result.token == "pooled-token"
        mock_client.get.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_http_client_creates_new_one(self) -> None:
        """Without http_client, a new AsyncClient should be created per call."""
        verifier = ServiceNowTokenVerifier(
            instance_url=INSTANCE_URL,
            cache_ttl_seconds=None,
        )
        mock_cls = _make_mock_client(response=_valid_sn_response())

        with patch("servicenow_mcp.auth.sn_token_verifier.httpx.AsyncClient", mock_cls):
            result = await verifier.verify_token("fresh-token")

        assert result is not None
        mock_cls.assert_called_once()
