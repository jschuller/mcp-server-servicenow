"""Tests for ServiceNow OAuth provider."""

from servicenow_mcp.auth.sn_oauth_provider import ServiceNowProvider
from servicenow_mcp.auth.sn_token_verifier import ServiceNowTokenVerifier


INSTANCE_URL = "https://dev12345.service-now.com"
CLIENT_ID = "test-client-id"
CLIENT_SECRET = "test-client-secret"
BASE_URL = "https://my-mcp-server.run.app"


class TestServiceNowProvider:
    def test_constructor_sets_sn_endpoints(self) -> None:
        """Provider should configure SN authorization and token endpoints."""
        provider = ServiceNowProvider(
            instance_url=INSTANCE_URL,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            base_url=BASE_URL,
        )
        assert provider._upstream_authorization_endpoint == f"{INSTANCE_URL}/oauth_auth.do"
        assert provider._upstream_token_endpoint == f"{INSTANCE_URL}/oauth_token.do"

    def test_upstream_client_credentials(self) -> None:
        """Provider should pass through the SN OAuth app credentials."""
        provider = ServiceNowProvider(
            instance_url=INSTANCE_URL,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            base_url=BASE_URL,
        )
        assert provider._upstream_client_id == CLIENT_ID
        assert provider._upstream_client_secret.get_secret_value() == CLIENT_SECRET

    def test_forward_pkce_enabled(self) -> None:
        """PKCE forwarding should be enabled (SN supports it since San Diego)."""
        provider = ServiceNowProvider(
            instance_url=INSTANCE_URL,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            base_url=BASE_URL,
        )
        assert provider._forward_pkce is True

    def test_token_endpoint_auth_method_is_client_secret_post(self) -> None:
        """SN expects client creds in POST body, not Basic header."""
        provider = ServiceNowProvider(
            instance_url=INSTANCE_URL,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            base_url=BASE_URL,
        )
        assert provider._token_endpoint_auth_method == "client_secret_post"

    def test_token_verifier_is_sn_type(self) -> None:
        """The token verifier should be a ServiceNowTokenVerifier."""
        provider = ServiceNowProvider(
            instance_url=INSTANCE_URL,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            base_url=BASE_URL,
        )
        assert isinstance(provider._token_validator, ServiceNowTokenVerifier)

    def test_instance_url_trailing_slash_stripped(self) -> None:
        """Trailing slash on instance URL should be normalized."""
        provider = ServiceNowProvider(
            instance_url=f"{INSTANCE_URL}/",
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            base_url=BASE_URL,
        )
        assert provider._upstream_authorization_endpoint == f"{INSTANCE_URL}/oauth_auth.do"

    def test_consent_required_by_default(self) -> None:
        """Consent screen should be required by default."""
        provider = ServiceNowProvider(
            instance_url=INSTANCE_URL,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            base_url=BASE_URL,
        )
        assert provider._require_authorization_consent is True

    def test_consent_can_be_disabled(self) -> None:
        """Consent screen can be disabled for dev/test environments."""
        provider = ServiceNowProvider(
            instance_url=INSTANCE_URL,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            base_url=BASE_URL,
            require_authorization_consent=False,
        )
        assert provider._require_authorization_consent is False
