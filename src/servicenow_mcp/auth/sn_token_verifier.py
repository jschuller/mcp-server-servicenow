"""ServiceNow token verifier for FastMCP OAuth proxy.

ServiceNow OAuth tokens are opaque (not JWTs), so we validate them by
making a lightweight API call to the instance. If the token is valid,
we get the authenticated user's info back.
"""

from __future__ import annotations

import logging

import httpx

from fastmcp.server.auth import TokenVerifier
from fastmcp.server.auth.auth import AccessToken

logger = logging.getLogger(__name__)


class ServiceNowTokenVerifier(TokenVerifier):
    """Verify ServiceNow opaque OAuth tokens via API call.

    Since SN tokens have no JWKS endpoint, we validate by calling
    ``GET /api/now/table/sys_user?sysparm_limit=1`` with the bearer token.
    A 200 response means the token is valid; anything else means it's not.
    """

    def __init__(
        self,
        *,
        instance_url: str,
        timeout_seconds: int = 10,
        required_scopes: list[str] | None = None,
    ) -> None:
        super().__init__(required_scopes=required_scopes)
        self.instance_url = instance_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify a ServiceNow OAuth token by calling the instance API."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                # Use current_user endpoint to validate token and get user info
                response = await client.get(
                    f"{self.instance_url}/api/now/ui/user/current_user",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                    },
                )

                if response.status_code != 200:
                    logger.debug(
                        "SN token verification failed: %d - %s",
                        response.status_code,
                        response.text[:200],
                    )
                    return None

                user_data = response.json().get("result", {})

                return AccessToken(
                    token=token,
                    client_id=user_data.get("user_name", "unknown"),
                    scopes=[],
                    expires_at=None,
                    claims={
                        "sub": user_data.get("user_sys_id", user_data.get("user_name")),
                        "user_name": user_data.get("user_name"),
                        "name": user_data.get("user_display_name"),
                        "email": user_data.get("user_email"),
                        "roles": user_data.get("roles"),
                        "sn_user_data": user_data,
                    },
                )

        except httpx.RequestError as e:
            logger.debug("Failed to verify SN token: %s", e)
            return None
        except Exception as e:
            logger.debug("SN token verification error: %s", e)
            return None
