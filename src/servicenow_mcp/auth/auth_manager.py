"""Authentication manager for the ServiceNow MCP server."""

import base64
import logging
from typing import Dict, Optional, Tuple

import requests

from servicenow_mcp.utils.config import AuthConfig, AuthType

logger = logging.getLogger(__name__)


class AuthManager:
    """Handles authentication with the ServiceNow API."""

    def __init__(
        self,
        config: AuthConfig,
        instance_url: Optional[str] = None,
        timeout: int = 30,
    ) -> None:
        self.config = config
        self.instance_url = instance_url
        self.timeout = timeout
        self.token: Optional[str] = None
        self.token_type: Optional[str] = None
        self._refresh_token: Optional[str] = None

    def get_headers(self) -> Dict[str, str]:
        """Get authentication headers for API requests."""
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        if self.config.type == AuthType.BASIC:
            if not self.config.basic:
                raise ValueError("Basic auth configuration is required")
            auth_str = f"{self.config.basic.username}:{self.config.basic.password}"
            encoded = base64.b64encode(auth_str.encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"

        elif self.config.type == AuthType.OAUTH:
            if not self.token:
                self._get_oauth_token()
            headers["Authorization"] = f"{self.token_type} {self.token}"

        elif self.config.type == AuthType.API_KEY:
            if not self.config.api_key:
                raise ValueError("API key configuration is required")
            headers[self.config.api_key.header_name] = self.config.api_key.api_key

        return headers

    def _token_endpoint(self) -> Tuple[str, Dict[str, str], Dict[str, str]]:
        """Return the token URL, headers and client-auth form fields for a grant.

        The client credentials grant sends the client id and secret in the form
        body (``client_secret_post``, the style proven against ServiceNow); the
        password and refresh grants keep HTTP Basic client authentication.
        """
        if not self.config.oauth:
            raise ValueError("OAuth configuration is required")
        oauth_config = self.config.oauth

        token_url = oauth_config.token_url
        if not token_url:
            if not self.instance_url:
                raise ValueError("Instance URL is required for OAuth authentication")
            token_url = f"{self.instance_url}/oauth_token.do"

        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        if oauth_config.grant_type == "client_credentials":
            client_fields = {
                "client_id": oauth_config.client_id,
                "client_secret": oauth_config.client_secret,
            }
            return token_url, headers, client_fields

        auth_str = f"{oauth_config.client_id}:{oauth_config.client_secret}"
        auth_header = base64.b64encode(auth_str.encode()).decode()
        headers["Authorization"] = f"Basic {auth_header}"
        return token_url, headers, {}

    def _store_token_response(self, response: requests.Response) -> None:
        """Store tokens from a successful (HTTP 200) token-endpoint response.

        A 200 without an ``access_token`` (an error body, an HTML login page from
        a hibernating instance) raises instead of storing ``None``, which would
        otherwise go out as ``Authorization: Bearer None`` (#12). The body is not
        echoed: it may carry token material. ServiceNow may rotate the refresh
        token on a refresh grant; when the response omits one, keep the one held.
        """
        try:
            token_data = response.json()
        except ValueError:
            token_data = None
        if not isinstance(token_data, dict) or not token_data.get("access_token"):
            raise ValueError(
                "OAuth token endpoint answered 200 without an access_token; "
                "check the client id/secret and that the instance is awake"
            )
        self.token = token_data["access_token"]
        self.token_type = token_data.get("token_type", "Bearer")
        self._refresh_token = token_data.get("refresh_token") or self._refresh_token

    def _get_oauth_token(self) -> None:
        """Get an OAuth token: the password grant with user credentials, else
        the client credentials grant."""
        if not self.config.oauth:
            raise ValueError("OAuth configuration is required")
        oauth_config = self.config.oauth
        token_url, headers, client_fields = self._token_endpoint()

        data: Dict[str, str] = {"grant_type": oauth_config.grant_type, **client_fields}
        if oauth_config.grant_type == "password":
            data["username"] = oauth_config.username or ""
            data["password"] = oauth_config.password or ""
        response = requests.post(
            token_url, headers=headers, data=data, timeout=self.timeout
        )

        if response.status_code == 200:
            self._store_token_response(response)
            return

        hint = ""
        if oauth_config.grant_type == "client_credentials":
            hint = (
                " (client credentials need the instance property "
                "glide.oauth.inbound.client.credential.grant_type.enabled=true and an "
                "OAuth Application User on the client record)"
            )
        raise ValueError(
            f"Failed to get OAuth token: {response.status_code} {response.text}{hint}"
        )

    def refresh_token(self) -> None:
        """Refresh the OAuth token if using OAuth authentication.

        Uses the refresh-token grant when a refresh token is held; falls back
        to a new grant of the configured type (password or client credentials)
        when the refresh grant fails (e.g. an expired or revoked refresh token)
        or none is held — client credentials tokens usually come without one.
        """
        if self.config.type != AuthType.OAUTH or not self.config.oauth:
            return
        grant = self.config.oauth.grant_type

        if self._refresh_token:
            token_url, headers, client_fields = self._token_endpoint()
            data = {
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
                **client_fields,
            }
            try:
                response = requests.post(
                    token_url, headers=headers, data=data, timeout=self.timeout
                )
                if response.status_code == 200:
                    self._store_token_response(response)
                    return
                logger.warning(
                    "OAuth refresh grant failed (%s); requesting a new %s grant",
                    response.status_code,
                    grant,
                )
            except (requests.RequestException, ValueError) as e:
                logger.warning(
                    "OAuth refresh grant errored (%s); requesting a new %s grant",
                    e,
                    grant,
                )
            # The held refresh token is dead; a new grant may store a new one.
            self._refresh_token = None

        self._get_oauth_token()
