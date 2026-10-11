"""Configuration module for the ServiceNow MCP server."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ServiceNow's default API-key auth parameter (a header or query parameter).
DEFAULT_API_KEY_HEADER = "x-sn-apikey"


class AuthType(str, Enum):
    """Authentication types supported by the ServiceNow MCP server."""

    BASIC = "basic"
    OAUTH = "oauth"
    API_KEY = "api_key"


class BasicAuthConfig(BaseModel):
    """Configuration for basic authentication."""

    username: str
    password: str


class OAuthConfig(BaseModel):
    """Configuration for OAuth authentication.

    With a username and password the server uses the password grant (legacy:
    it skips MFA); without them, the client credentials grant, which acts as
    the OAuth client's application user.
    """

    client_id: str
    client_secret: str
    username: Optional[str] = None
    password: Optional[str] = None
    token_url: Optional[str] = None

    @property
    def grant_type(self) -> str:
        """``password`` with user credentials, else ``client_credentials``."""
        return "password" if self.username and self.password else "client_credentials"


class ApiKeyConfig(BaseModel):
    """Configuration for API key authentication."""

    api_key: str
    header_name: str = DEFAULT_API_KEY_HEADER


class AuthConfig(BaseModel):
    """Authentication configuration."""

    type: AuthType
    basic: Optional[BasicAuthConfig] = None
    oauth: Optional[OAuthConfig] = None
    api_key: Optional[ApiKeyConfig] = None


class ServerConfig(BaseModel):
    """Server configuration."""

    instance_url: str
    auth: AuthConfig
    debug: bool = False
    timeout: int = 30

    # --- Safety rails (v0.7.0) ---
    read_only: bool = Field(
        default=False,
        description="Hide write tools and refuse non-GET ServiceNow requests.",
    )
    allow_js_queries: bool = Field(
        default=False,
        description="Permit arbitrary javascript: expressions in caller-supplied queries.",
    )
    audit_log: str = Field(
        default="stderr",
        description="Audit log target: 'stderr', 'off', or a file path.",
    )

    @property
    def api_url(self) -> str:
        """Get the API URL for the ServiceNow instance."""
        return f"{self.instance_url}/api/now"
