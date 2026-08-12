"""ServiceNow token verifier for FastMCP OAuth proxy.

ServiceNow OAuth tokens are opaque (not JWTs), so we validate them by
making a lightweight API call to the instance. If the token is valid,
we get the authenticated user's info back.

Supports optional in-memory caching (default 5 min TTL) and connection
pooling via a shared ``httpx2.AsyncClient``.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import time
from dataclasses import dataclass

import httpx2

from fastmcp.server.auth import AccessToken, TokenVerifier

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _CacheEntry:
    result: AccessToken
    expires_at: float


class ServiceNowTokenVerifier(TokenVerifier):
    """Verify ServiceNow opaque OAuth tokens via API call.

    Since SN tokens have no JWKS endpoint, we validate by calling
    ``GET /api/now/table/sys_user?sysparm_limit=1`` with the bearer token.
    A 200 response means the token is valid; anything else means it's not.

    Features:
        - **Caching**: Verified tokens are cached by SHA-256 hash for
          ``cache_ttl_seconds`` (default 300s / 5 min). Set to ``None`` to
          disable caching.
        - **Connection pooling**: Pass a shared ``httpx2.AsyncClient`` to
          reuse HTTP connections across verification calls.
    """

    _DEFAULT_MAX_CACHE_SIZE = 1000

    def __init__(
        self,
        *,
        instance_url: str,
        timeout_seconds: int = 10,
        required_scopes: list[str] | None = None,
        http_client: httpx2.AsyncClient | None = None,
        cache_ttl_seconds: int | None = 300,
        max_cache_size: int | None = None,
    ) -> None:
        super().__init__(required_scopes=required_scopes)
        self.instance_url = instance_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._http_client = http_client
        self._cache_ttl = cache_ttl_seconds
        self._max_cache_size = max_cache_size or self._DEFAULT_MAX_CACHE_SIZE
        self._cache: dict[str, _CacheEntry] = {}

    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify a ServiceNow OAuth token by calling the instance API."""
        # Check cache first
        cache_key: str | None = None
        if self._cache_ttl is not None:
            cache_key = hashlib.sha256(token.encode()).hexdigest()
            entry = self._cache.get(cache_key)
            if entry is not None and entry.expires_at > time.monotonic():
                return entry.result

        result = await self._call_sn_api(token)

        # Cache successful verification
        if result is not None and cache_key is not None and self._cache_ttl is not None:
            if len(self._cache) >= self._max_cache_size:
                self._evict_expired()
            self._cache[cache_key] = _CacheEntry(
                result=result,
                expires_at=time.monotonic() + self._cache_ttl,
            )

        return result

    async def _call_sn_api(self, token: str) -> AccessToken | None:
        """Make the SN API call to validate the token."""
        try:
            cm = (
                contextlib.nullcontext(self._http_client)
                if self._http_client is not None
                else httpx2.AsyncClient(timeout=self.timeout_seconds)
            )
            async with cm as client:
                response = await client.get(
                    f"{self.instance_url}/api/now/table/sys_user",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                    },
                    params={
                        "sysparm_query": "user_name=javascript:gs.getUserName()",
                        "sysparm_limit": 1,
                        "sysparm_fields": "user_name,name,email,sys_id,roles",
                    },
                )

                if response.status_code != 200:
                    logger.debug(
                        "SN token verification failed: %d - %s",
                        response.status_code,
                        response.text[:200],
                    )
                    return None

                results = response.json().get("result", [])
                if not results:
                    logger.debug("SN token valid but no user record returned")
                    return None

                user = results[0]

                return AccessToken(
                    token=token,
                    client_id=user.get("user_name", "unknown"),
                    scopes=[],
                    expires_at=None,
                    claims={
                        "sub": user.get("sys_id", user.get("user_name")),
                        "user_name": user.get("user_name"),
                        "name": user.get("name"),
                        "email": user.get("email"),
                        "roles": user.get("roles"),
                        "sn_user_data": user,
                    },
                )

        except httpx2.RequestError as e:
            logger.debug("Failed to verify SN token: %s", e)
            return None
        except Exception as e:
            logger.debug("SN token verification error: %s", e)
            return None

    def _evict_expired(self) -> None:
        """Remove expired entries from the cache."""
        now = time.monotonic()
        self._cache = {k: v for k, v in self._cache.items() if v.expires_at > now}
