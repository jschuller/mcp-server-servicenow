"""HTTP request helper with proper error handling for ServiceNow API responses."""

import logging
from typing import Any, Dict, Optional

import requests

from servicenow_mcp.auth.auth_manager import AuthManager

logger = logging.getLogger(__name__)

# ServiceNow response headers that aid debugging
_DIAGNOSTIC_HEADERS = ("X-Is-Logged-In", "X-Transaction-ID")


class ServiceNowAPIError(Exception):
    """Raised when the ServiceNow API returns an unexpected response."""


def _error_context(response: "requests.Response") -> str:
    """Extract diagnostic context from a ServiceNow error response.

    Returns a string with response body preview and key headers.
    """
    parts: list[str] = []

    body = response.text[:500] if response.text else None
    if body:
        parts.append(f"Response: {body}")

    diag = {
        h: response.headers[h] for h in _DIAGNOSTIC_HEADERS if h in response.headers
    }
    if diag:
        parts.append(f"Headers: {diag}")

    return " | ".join(parts) if parts else ""


def api_request(
    method: str,
    url: str,
    auth_manager: Optional[AuthManager] = None,
    timeout: int = 30,
    params: Optional[Dict[str, Any]] = None,
    json_data: Optional[Dict[str, Any]] = None,
    bearer_token: Optional[str] = None,
) -> requests.Response:
    """Make an HTTP request to the ServiceNow API with proper error handling.

    Raises ServiceNowAPIError with a descriptive message instead of
    letting json.JSONDecodeError bubble up from empty/HTML responses.

    On a 401 response with OAuth auth, automatically refreshes the token
    and retries the request once.

    When ``bearer_token`` is set, uses ``Authorization: Bearer <token>``
    directly instead of the auth manager. This supports per-user OAuth
    proxy tokens.
    """
    if bearer_token:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {bearer_token}",
        }
    elif auth_manager:
        headers = auth_manager.get_headers()
    else:
        raise ServiceNowAPIError("Either auth_manager or bearer_token must be provided")

    try:
        response = requests.request(
            method=method,
            url=url,
            headers=headers,
            params=params,
            json=json_data,
            timeout=timeout,
        )
    except requests.ConnectionError as e:
        raise ServiceNowAPIError(
            f"Cannot connect to ServiceNow at {url}. "
            f"Check that the instance URL is correct and the instance is awake. "
            f"Detail: {e}"
        ) from e
    except requests.Timeout as e:
        raise ServiceNowAPIError(
            f"Request to {url} timed out after {timeout}s. "
            f"The instance may be hibernating or overloaded."
        ) from e

    # On 401, attempt one token refresh and retry (OAuth only, not for bearer tokens)
    if response.status_code == 401:
        if bearer_token:
            ctx = _error_context(response)
            raise ServiceNowAPIError(
                f"Authentication failed (401). The per-user OAuth token may be expired. "
                f"URL: {url}" + (f" | {ctx}" if ctx else "")
            )
        if auth_manager and auth_manager.config.type.value == "oauth":
            logger.info("Got 401, attempting OAuth token refresh and retry")
            try:
                auth_manager.refresh_token()
            except Exception as e:
                raise ServiceNowAPIError(
                    f"Authentication failed (401) and token refresh also failed. "
                    f"URL: {url}. Refresh error: {e}"
                ) from e

            # Retry with fresh headers
            headers = auth_manager.get_headers()
            try:
                response = requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=json_data,
                    timeout=timeout,
                )
            except (requests.ConnectionError, requests.Timeout) as e:
                raise ServiceNowAPIError(
                    f"Retry after token refresh failed: {e}"
                ) from e

            if response.status_code == 401:
                ctx = _error_context(response)
                raise ServiceNowAPIError(
                    f"Authentication failed (401) even after token refresh. "
                    f"Check your OAuth credentials. URL: {url}"
                    + (f" | {ctx}" if ctx else "")
                )
        else:
            ctx = _error_context(response)
            raise ServiceNowAPIError(
                f"Authentication failed (401). Check your username/password. "
                f"URL: {url}" + (f" | {ctx}" if ctx else "")
            )

    if response.status_code == 403:
        ctx = _error_context(response)
        raise ServiceNowAPIError(
            f"Access denied (403). The user may lack permissions for this API. "
            f"URL: {url}" + (f" | {ctx}" if ctx else "")
        )
    if response.status_code == 404:
        ctx = _error_context(response)
        raise ServiceNowAPIError(
            f"Not found (404). The table or record may not exist. "
            f"URL: {url}" + (f" | {ctx}" if ctx else "")
        )

    # For other errors, raise with response body context
    if not response.ok:
        body_preview = response.text[:500] if response.text else "(empty)"
        raise ServiceNowAPIError(
            f"HTTP {response.status_code} from {url}. Response: {body_preview}"
        )

    return response


def parse_json_response(response: requests.Response, url: str) -> Dict[str, Any]:
    """Parse a JSON response, raising ServiceNowAPIError on failure."""
    if not response.text or not response.text.strip():
        raise ServiceNowAPIError(
            f"Empty response body from {url} (HTTP {response.status_code}). "
            f"The instance may be hibernating — wake it at developer.servicenow.com"
        )

    content_type = response.headers.get("Content-Type", "")
    if "text/html" in content_type:
        raise ServiceNowAPIError(
            f"Got HTML instead of JSON from {url}. "
            f"This usually means the instance is showing a login page. "
            f"Check credentials or wake the instance at developer.servicenow.com"
        )

    try:
        return response.json()
    except ValueError as e:
        body_preview = response.text[:200]
        raise ServiceNowAPIError(
            f"Invalid JSON from {url}: {e}. Response starts with: {body_preview!r}"
        ) from e
