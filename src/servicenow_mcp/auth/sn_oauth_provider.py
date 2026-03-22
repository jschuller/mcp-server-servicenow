"""ServiceNow OAuth provider for FastMCP.

Thin OAuthProxy subclass that configures ServiceNow's OAuth 2.0 endpoints.
Follows the same pattern as FastMCP's built-in GitHubProvider.

End users authenticate with their own ServiceNow credentials. The proxy
exchanges the SN auth code for SN tokens server-side, stores them encrypted,
then issues its own signed JWTs to the MCP client.

Requirements:
    - ServiceNow San Diego+ (2022) for PKCE support
    - OAuth application registered in SN Application Registry
    - Redirect URI: ``{base_url}/auth/callback``
"""

from __future__ import annotations

import logging

import httpx
from pydantic import AnyHttpUrl

from fastmcp.server.auth.oauth_proxy import OAuthProxy

from servicenow_mcp.auth.sn_token_verifier import ServiceNowTokenVerifier

logger = logging.getLogger(__name__)


class ServiceNowProvider(OAuthProxy):
    """OAuth 2.1 + PKCE provider for ServiceNow instances.

    Proxies the MCP client's OAuth flow to a ServiceNow instance so that each
    user authenticates with their own SN credentials. Per-user ACLs apply to
    every tool call.

    Example::

        from servicenow_mcp.auth.sn_oauth_provider import ServiceNowProvider

        auth = ServiceNowProvider(
            instance_url="https://dev12345.service-now.com",
            client_id="<from SN Application Registry>",
            client_secret="<from SN Application Registry>",
            base_url="https://my-mcp-server.run.app",
        )
        mcp = FastMCP("servicenow-mcp", auth=auth)
    """

    def __init__(
        self,
        *,
        instance_url: str,
        client_id: str,
        client_secret: str,
        base_url: AnyHttpUrl | str,
        issuer_url: AnyHttpUrl | str | None = None,
        redirect_path: str | None = None,
        timeout_seconds: int = 10,
        allowed_client_redirect_uris: list[str] | None = None,
        jwt_signing_key: str | bytes | None = None,
        require_authorization_consent: bool = True,
    ) -> None:
        """Initialize ServiceNow OAuth provider.

        Args:
            instance_url: ServiceNow instance URL (e.g. ``https://dev12345.service-now.com``)
            client_id: OAuth app client ID from SN Application Registry
            client_secret: OAuth app client secret from SN Application Registry
            base_url: Public URL of this MCP server (used for redirect URI)
            issuer_url: Issuer URL for OAuth metadata (defaults to base_url)
            redirect_path: Redirect path (defaults to ``/auth/callback``)
            timeout_seconds: HTTP timeout for SN API calls during token verification
            allowed_client_redirect_uris: Allowed redirect URI patterns for MCP clients
            jwt_signing_key: Secret for signing FastMCP JWTs (derived from client_secret if omitted)
            require_authorization_consent: Show consent screen before redirecting to SN (default True)
        """
        instance_url = instance_url.rstrip("/")

        shared_http_client = httpx.AsyncClient(timeout=timeout_seconds)

        token_verifier = ServiceNowTokenVerifier(
            instance_url=instance_url,
            timeout_seconds=timeout_seconds,
            http_client=shared_http_client,
        )

        super().__init__(
            # ServiceNow OAuth endpoints
            upstream_authorization_endpoint=f"{instance_url}/oauth_auth.do",
            upstream_token_endpoint=f"{instance_url}/oauth_token.do",
            upstream_client_id=client_id,
            upstream_client_secret=client_secret,
            # Token validation
            token_verifier=token_verifier,
            # Server config
            base_url=base_url,
            redirect_path=redirect_path,
            issuer_url=issuer_url or base_url,
            # Client config
            allowed_client_redirect_uris=allowed_client_redirect_uris,
            # SN supports PKCE (San Diego+ / 2022)
            forward_pkce=True,
            # SN expects client creds in POST body, not Basic header
            token_endpoint_auth_method="client_secret_post",
            # JWT signing
            jwt_signing_key=jwt_signing_key,
            # Consent screen
            require_authorization_consent=require_authorization_consent,
        )

        logger.info(
            "Initialized ServiceNow OAuth provider for %s",
            instance_url,
        )
