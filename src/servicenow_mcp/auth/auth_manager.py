"""Authentication manager for the ServiceNow MCP server."""

import base64
import logging
from typing import Dict, Optional

import requests

from servicenow_mcp.utils.config import AuthConfig, AuthType

logger = logging.getLogger(__name__)


class AuthManager:
    """Handles authentication with the ServiceNow API."""

    def __init__(self, config: AuthConfig, instance_url: Optional[str] = None) -> None:
        self.config = config
        self.instance_url = instance_url
        self.token: Optional[str] = None
        self.token_type: Optional[str] = None

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

    def _get_oauth_token(self) -> None:
        """Get an OAuth token from ServiceNow."""
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

        # Try password grant
        data = {
            "grant_type": "password",
            "username": oauth_config.username,
            "password": oauth_config.password,
        }
        response = requests.post(token_url, headers=headers, data=data)

        if response.status_code == 200:
            token_data = response.json()
            self.token = token_data.get("access_token")
            self.token_type = token_data.get("token_type", "Bearer")
            return

        raise ValueError(
            f"Failed to get OAuth token: {response.status_code} {response.text}"
        )

    def refresh_token(self) -> None:
        """Refresh the OAuth token if using OAuth authentication."""
        if self.config.type == AuthType.OAUTH:
            self._get_oauth_token()
