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

    def _token_endpoint(self) -> Tuple[str, Dict[str, str]]:
        """Return the token URL and client-auth headers for OAuth grants."""
        if not self.config.oauth:
            raise ValueError("OAuth configuration is required")
        oauth_config = self.config.oauth

        token_url = oauth_config.token_url
        if not token_url:
            if not self.instance_url:
                raise ValueError("Instance URL is required for OAuth authentication")
            token_url = f"{self.instance_url}/oauth_token.do"

        auth_str = f"{oauth_config.client_id}:{oauth_config.client_secret}"
        auth_header = base64.b64encode(auth_str.encode()).decode()
        headers = {
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        return token_url, headers

    def _store_token_response(self, token_data: Dict) -> None:
        """Store tokens from a successful token-endpoint response.

        ServiceNow may rotate the refresh token on a refresh grant; when the
        response omits one, keep the refresh token already held.
        """
        self.token = token_data.get("access_token")
        self.token_type = token_data.get("token_type", "Bearer")
        self._refresh_token = token_data.get("refresh_token") or self._refresh_token

    def _get_oauth_token(self) -> None:
        """Get an OAuth token from ServiceNow via the password grant."""
        if not self.config.oauth:
            raise ValueError("OAuth configuration is required")
        oauth_config = self.config.oauth
        token_url, headers = self._token_endpoint()

        data = {
            "grant_type": "password",
            "username": oauth_config.username,
            "password": oauth_config.password,
        }
        response = requests.post(
            token_url, headers=headers, data=data, timeout=self.timeout
        )

        if response.status_code == 200:
            self._store_token_response(response.json())
            return

        raise ValueError(
            f"Failed to get OAuth token: {response.status_code} {response.text}"
        )

    def refresh_token(self) -> None:
        """Refresh the OAuth token if using OAuth authentication.

        Uses the refresh-token grant when a refresh token is held; falls back
        to a full password grant when the refresh grant fails (e.g. an expired
        or revoked refresh token).
        """
        if self.config.type != AuthType.OAUTH:
            return

        if self._refresh_token:
            token_url, headers = self._token_endpoint()
            data = {
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
            }
            try:
                response = requests.post(
                    token_url, headers=headers, data=data, timeout=self.timeout
                )
                if response.status_code == 200:
                    self._store_token_response(response.json())
                    return
                logger.warning(
                    "OAuth refresh grant failed (%s); falling back to password grant",
                    response.status_code,
                )
            except requests.RequestException as e:
                logger.warning(
                    "OAuth refresh grant errored (%s); falling back to password grant",
                    e,
                )
            # The held refresh token is dead; the password grant stores a new one.
            self._refresh_token = None

        self._get_oauth_token()
