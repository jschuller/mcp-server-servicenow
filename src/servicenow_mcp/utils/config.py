"""Configuration module for the ServiceNow MCP server."""

import re
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ServiceNow's default API-key auth parameter (a header or query parameter).
DEFAULT_API_KEY_HEADER = "x-sn-apikey"


HEADER_NAME = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+\Z")


def header_value_problem(value: str) -> Optional[str]:
    """Why ``value`` cannot be sent as an HTTP header value, or None.

    The answer never repeats the value: it is a credential.
    """
    if value != value.strip():
        return "white space at its start or end (often a pasted line ending)"
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return "a control character (often a pasted line ending)"
    try:
        value.encode("latin-1")
    except UnicodeEncodeError:
        return "a character HTTP headers cannot carry"
    return None


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
    skills: bool = Field(
        default=True,
        description=(
            "Serve the packaged skills (skill:// resources, the query-syntax alias) "
            "and name them in the server instructions."
        ),
    )
    apps: bool = Field(
        default=False,
        description=(
            "Register the MCP Apps views (ui:// resources) and the tools that "
            "open them. Off by default: a spike."
        ),
    )

    @property
    def api_url(self) -> str:
        """Get the API URL for the ServiceNow instance."""
        return f"{self.instance_url}/api/now"
