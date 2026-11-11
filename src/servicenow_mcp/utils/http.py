"""HTTP request helper with proper error handling for ServiceNow API responses.

What an error message shows depends on who reads it. Over stdio the MCP client
is the process that launched this server and gave it the instance URL, so the
message names the URL, ServiceNow's diagnostic headers and the low-level cause.
Everywhere else (HTTP, SSE, an in-process client, a library call) the reader
may be remote: the message keeps the status, ServiceNow's own error message,
the API path and the hints, and leaves out the instance host and the headers.

Three things are in none of this server's error text, in none of the log lines
it writes and not in its audit line. A response body is never quoted: it can
hold a record's field values (a system property's value, say), so only the
``error.message`` and ``error.detail`` of ServiceNow's JSON error are shown,
and any other body is described by its content type, its length and whether
it parsed. A query string is never shown: it can carry filter values. And the
text of a requests, urllib3 or http.client exception is never used: it can
quote either of those, or a header this server sent (``utils/causes.py``).

That is a statement about this server's own text. The libraries below it log
on their own: the CLI keeps them quiet at the default level, and ``--debug``
lets them print request lines with their query strings.
"""

import logging
import re
import socket
from contextlib import contextmanager
from contextvars import ContextVar
from urllib.parse import quote, urlsplit
from typing import Any, Dict, Iterator, Mapping, Optional

import requests
from fastmcp.exceptions import ToolError

from servicenow_mcp.auth.auth_manager import AuthError, AuthManager
from servicenow_mcp.utils.causes import cause_chain
from servicenow_mcp.utils.config import HEADER_NAME, header_value_problem

logger = logging.getLogger(__name__)

# ServiceNow response headers that aid debugging
_DIAGNOSTIC_HEADERS = ("X-Is-Logged-In", "X-Transaction-ID")

# Absolute links, so a model can pass them on to the user from any client.
_DOCS = "https://github.com/jschuller/mcp-server-servicenow/blob/main"
_TROUBLESHOOTING = f"{_DOCS}/TROUBLESHOOTING.md"
_PDI_WAKE_URL = "https://developer.servicenow.com/dev.do#!/home?wu=true"

_CAUSE_MAX = 500  # characters of a low-level cause in a local message
_QUERY_STRING = re.compile(r"\?[\w.%~+-]+=\S*")
_PART_MAX = 300  # characters of ServiceNow's message or detail, or of a cause


class ServiceNowAPIError(ToolError):
    """A ServiceNow request failed in a way the caller can act on.

    A FastMCP ``ToolError``: a tool that lets it propagate returns this message
    as it is in a result with ``isError: true`` (a resource read returns it as
    a JSON-RPC error), and FastMCP logs no traceback for it. FastMCP's own log
    line for the failure is set to DEBUG, because ``ApiErrorMiddleware`` writes
    the one WARNING line, with ``details`` and ``diagnostics``.

    ``status`` is the HTTP status when ServiceNow answered, else None.
    ``details`` holds the parts of the message that any client may see, as
    data: ``kind``, ``status``, ``method``, ``path``, ``sn_message``,
    ``sn_detail`` and ``hint``, each only when known. ``diagnostics`` holds what
    only the operator's log gets: ServiceNow's diagnostic ``headers``, what the
    ``body`` was when it is not ServiceNow's JSON error (type, length, parsed or
    not: never its content), and the low-level ``cause`` (the exception classes
    and an errno, never a library's own text). Neither holds a query string,
    body content or a credential.
    """

    def __init__(
        self,
        message: str,
        *,
        status: Optional[int] = None,
        details: Optional[Mapping[str, Any]] = None,
        diagnostics: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(message, log_level=logging.DEBUG)
        self.status = status
        self.details: Dict[str, Any] = dict(details or {})
        self.diagnostics: Dict[str, Any] = dict(diagnostics or {})


_local_detail: ContextVar[bool] = ContextVar(
    "servicenow_mcp_local_detail", default=False
)


@contextmanager
def local_error_detail() -> Iterator[None]:
    """Full error detail for a caller that is local by construction (``--check``)."""
    token = _local_detail.set(True)
    try:
        yield
    finally:
        _local_detail.reset(token)


def _local_reader() -> bool:
    """True when the reader of an error message is the local user.

    That is an MCP request FastMCP reports as stdio (the client launched this
    process and gave it the instance URL, so naming the host tells it nothing
    new) or a caller inside ``local_error_detail()``. Anything else gets the
    trimmed message: when the transport is not known, assume a remote reader.
    """
    if _local_detail.get():
        return True
    try:
        from fastmcp.server.dependencies import get_context

        return get_context().transport == "stdio"
    except RuntimeError:  # no MCP request is active
        return False


def error_target(url: str) -> str:
    """How an error message names a request: the URL for a local reader, else
    only its path. Never the query string."""
    parts = urlsplit(url)
    if not _local_reader():
        return parts.path or "/"
    return f"{parts.scheme}://{parts.netloc}{parts.path}" if parts.netloc else url


def _clip(text: object, limit: int = _PART_MAX) -> str:
    """``text`` on one line, without query strings, at most ``limit`` characters."""
    flat = " ".join(_QUERY_STRING.sub("", str(text)).split())
    return flat if len(flat) <= limit else flat[:limit] + "…"


def _diagnostic_headers(response: "requests.Response") -> Dict[str, str]:
    return {
        h: response.headers[h] for h in _DIAGNOSTIC_HEADERS if h in response.headers
    }


def _sn_error(response: "requests.Response") -> Dict[str, str]:
    """ServiceNow's own error message and detail, when the body is its JSON error.

    Only ``{"error": {"message": ..., "detail": ...}}`` counts: nothing else in
    a body is ever shown.
    """
    try:
        body = response.json()
    except ValueError:
        return {}
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return {}
    found: Dict[str, str] = {}
    for key in ("message", "detail"):
        value = error.get(key)
        if isinstance(value, str) and value.strip():
            found[f"sn_{key}"] = _clip(value)
    return found


def _body_summary(response: "requests.Response") -> str:
    """What a body was, never what it said: its content type, length and shape.

    A body that stops being JSON part-way gets the parser's position, as a
    number: the parser's own message is not used, and neither is its ``doc``.
    """
    if not response.text:
        return "(empty)"
    content_type = response.headers.get("Content-Type", "").split(";")[0].strip()
    try:
        response.json()
        shape = "not a ServiceNow error object"
    except ValueError as e:
        position = getattr(e, "pos", None)
        if isinstance(position, int) and position > 0:
            shape = f"invalid JSON at position {position}"
        else:
            shape = "not JSON"
    return (
        f"{content_type or 'no content type'}, {len(response.text)} characters, "
        f"{shape}, not shown"
    )


def response_summary(response: Any) -> str:
    """What a response said, in words that are safe for a message or a log line.

    ServiceNow's parsed error message and detail; any other body, an empty one
    included, is described, never quoted. ``response`` is a requests or an
    httpx2 response.
    """
    sn_error = _sn_error(response)
    if sn_error:
        return "ServiceNow error: " + ": ".join(sn_error.values())
    return f"Response: {_body_summary(response)}"


def _error_context(response: "requests.Response") -> str:
    """What ServiceNow answered, as the tail of an error message.

    ServiceNow's parsed error message and detail; any other body, an empty
    one included, is described, not quoted (an HTML page, a truncated or
    unexpected JSON body can hold record values or name hosts). A local reader
    also gets the diagnostic headers.
    """
    parts = [response_summary(response)]
    if _local_reader():
        diag = _diagnostic_headers(response)
        if diag:
            parts.append(f"Headers: {diag}")
    return " | ".join(parts)


def error_text(error: BaseException) -> str:
    """An error in words that are safe to show and to log.

    This server's own errors keep the text it wrote for them. Anything else,
    a requests, urllib3 or http.client exception above all, is named by its
    classes only: its text can quote response bytes, a header value or a
    query string.
    """
    if isinstance(error, (ToolError, AuthError)):
        return _clip(error, _CAUSE_MAX)
    return cause_chain(error)


def _cause(error: BaseException, label: str = "Detail") -> str:
    """The low-level cause as a message tail, for a local reader."""
    return f" {label}: {error_text(error)}" if _local_reader() else ""


def _check_headers(headers: Mapping[str, str]) -> Optional[str]:
    """What is wrong with the headers this server is about to send, or None.

    requests would refuse them too, but its error quotes the value.
    """
    for name, value in headers.items():
        if not HEADER_NAME.match(name):
            return (
                "a header this server would send has a name HTTP does not allow; "
                "check the configured API key header name"
            )
        problem = header_value_problem(value)
        if problem:
            return (
                f"the {name} header this server would send holds {problem}; "
                "set the credential again (its value is not shown)"
            )
    return None


def _mask_host(text: str, url: str) -> str:
    """``text`` without the instance's host, however it is written there:
    any case, a trailing dot, an explicit port."""
    host = (urlsplit(url).hostname or "").rstrip(".")
    if not host:
        return text
    return re.sub(
        re.escape(host) + r"\.?(?::\d+)?(?![\w-])", "<instance>", text, flags=re.I
    )


def _failure(
    kind: str,
    message: str,
    *,
    url: str,
    method: Optional[str] = None,
    response: Optional["requests.Response"] = None,
    hint: Optional[str] = None,
    cause: Optional[BaseException] = None,
) -> ServiceNowAPIError:
    """The error for one failed request: the message, and the same facts as data."""
    parts = urlsplit(url)
    details: Dict[str, Any] = {"kind": kind}
    diagnostics: Dict[str, Any] = {}
    status: Optional[int] = None
    if response is not None:
        status = response.status_code
        details["status"] = status
    if method:
        details["method"] = method.upper()
    details["path"] = parts.path or "/"
    if response is not None:
        sn_error = _sn_error(response)
        details.update(sn_error)
        headers = _diagnostic_headers(response)
        if headers:
            diagnostics["headers"] = headers
        if not sn_error:
            diagnostics["body"] = _body_summary(response)
    if hint:
        details["hint"] = hint
    if cause is not None:
        diagnostics["cause"] = error_text(cause)
    if not _local_reader():
        # The message was built without the host; this keeps it out even when
        # ServiceNow's own error text names it.
        message = _mask_host(message, url)
        for key in ("sn_message", "sn_detail"):
            if key in details:
                details[key] = _mask_host(details[key], url)
    return ServiceNowAPIError(
        message, status=status, details=details, diagnostics=diagnostics
    )


def _is_name_resolution_error(error: BaseException) -> bool:
    """True when a connection error comes from DNS (a typo or a reclaimed PDI)."""
    seen: set[int] = set()
    pending: list[BaseException] = [error]
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, socket.gaierror):
            return True
        # requests wraps urllib3's MaxRetryError, whose ``reason`` chains to gaierror
        nested = (
            *current.args,
            getattr(current, "reason", None),
            current.__cause__,
            current.__context__,
        )
        pending.extend(x for x in nested if isinstance(x, BaseException))
    return False


def build_url(base: str, *segments: str) -> str:
    """Join URL path segments onto ``base``, percent-encoding each segment.

    Identifiers such as table names and sys_ids come from tool arguments; encoding
    them means ``../`` or ``?sysparm_query=`` can never rewrite the request path.
    """
    return base + "".join("/" + quote(str(segment), safe="") for segment in segments)


_TABLE_RECORD_PATH = re.compile(r"/api/now/table/[^/?]+/[0-9a-f]{32}(?:$|\?)")


def api_key_401_hint(method: str, url: str) -> str:
    """What to check, and what still works, after an API key's 401.

    API keys only authenticate where a REST API access policy maps the key's
    profile for this API and method; the global policy cannot carry token
    auth, so each API needs its own policy. A key that reads tables often has
    no policy for the Stats API or single-record reads, so say which table
    read gets the same answer instead of leaving the agent to give up.
    """
    hint = (
        "Check the API key and that a REST API access policy maps it "
        f"for this API and method ({method.upper()})."
    )
    if method.upper() != "GET":
        return hint
    if "/api/now/stats/" in url:
        return hint + (
            " Table reads may still work with this key: count with list_records "
            '(the same query, fields="sys_id", limit=1000, paging with offset) '
            "instead of aggregate_records."
        )
    if _TABLE_RECORD_PATH.search(url):
        return hint + (
            " Table reads may still work with this key: list_records with "
            'query="sys_id=<the sys_id>" and limit=1 returns the same record.'
        )
    return hint


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
    where = error_target(url)

    def failure(kind: str, message: str, **facts: Any) -> ServiceNowAPIError:
        return _failure(kind, message, url=url, method=method, **facts)

    def refused(
        kind: str,
        message: str,
        response: requests.Response,
        hint: Optional[str] = None,
    ) -> ServiceNowAPIError:
        """A refusal ServiceNow answered: the message ends with where and what it said."""
        ctx = _error_context(response)
        return failure(
            kind,
            f"{message} URL: {where}" + (f" | {ctx}" if ctx else ""),
            response=response,
            hint=hint,
        )

    if bearer_token:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {bearer_token}",
        }
    elif auth_manager:
        try:
            headers = auth_manager.get_headers()
        except AuthError as e:
            # The token endpoint refused the grant or answered without a token.
            raise failure(
                "token_request",
                error_text(e)
                if _local_reader()
                else "Could not get an OAuth token for the ServiceNow identity this "
                "server uses; the server's log has the token endpoint's answer.",
                cause=e,
            ) from e
        except (requests.RequestException, ValueError) as e:
            # The first OAuth token is requested here. ``from None``: a
            # traceback would print the library's text.
            raise failure(
                "connection",
                "Cannot connect to ServiceNow to get an OAuth token. Check that the "
                "instance URL is correct and the instance is awake." + _cause(e),
                cause=e,
            ) from None
    else:
        raise ServiceNowAPIError("Either auth_manager or bearer_token must be provided")

    problem = _check_headers(headers)
    if problem:
        raise failure("credentials", f"Request to {where} not sent: {problem}.")

    try:
        response = requests.request(
            method=method,
            url=url,
            headers=headers,
            params=params,
            json=json_data,
            timeout=timeout,
        )
    except requests.exceptions.SSLError as e:
        raise failure(
            "tls",
            f"TLS certificate check failed for {where}. Behind a proxy that inspects "
            f"TLS, set REQUESTS_CA_BUNDLE to your company's CA bundle. "
            f"See {_TROUBLESHOOTING}#certificate-verify-failed." + _cause(e),
            cause=e,
        ) from None
    except requests.ConnectionError as e:
        if _is_name_resolution_error(e):
            subject = (
                f"the host in {where}"
                if _local_reader()
                else f"the host in the instance URL (request to {where})"
            )
            raise failure(
                "dns",
                f"Cannot resolve {subject}. Check the instance URL for a typo; "
                f"a reclaimed PDI no longer resolves. "
                f"See {_TROUBLESHOOTING}#instance-not-found." + _cause(e),
                cause=e,
            ) from None
        raise failure(
            "connection",
            f"Cannot connect to ServiceNow at {where}. "
            f"Check that the instance URL is correct and the instance is awake."
            + _cause(e),
            cause=e,
        ) from None
    except requests.Timeout as e:
        raise failure(
            "timeout",
            f"Request to {where} timed out after {timeout}s. "
            f"The instance may be hibernating or overloaded.",
            cause=e,
        ) from None
    except Exception as e:
        # Too many redirects, a broken transfer encoding, an answer that is
        # not HTTP, and whatever else the HTTP stack raises: named by class.
        raise failure(
            "request", f"Request to {where} failed ({cause_chain(e)}).", cause=e
        ) from None

    # On 401, attempt one token refresh and retry (OAuth only, not for bearer tokens)
    if response.status_code == 401:
        if bearer_token:
            raise refused(
                "unauthorized",
                "Authentication failed (401) for the bearer-token request. "
                "The token may be expired or not valid for this instance.",
                response,
            )
        if auth_manager and auth_manager.config.type.value == "oauth":
            logger.info("Got 401, attempting OAuth token refresh and retry")
            try:
                auth_manager.refresh_token()
            except Exception as e:
                raise failure(
                    "token_refresh",
                    f"Authentication failed (401) and token refresh also failed. "
                    f"URL: {where}." + _cause(e, "Refresh error"),
                    response=response,
                    cause=e,
                ) from None

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
            except Exception as e:
                raise failure(
                    "connection",
                    "Retry after token refresh failed: the instance did not answer "
                    f"({cause_chain(e)}).",
                    cause=e,
                ) from None

            if response.status_code == 401:
                raise refused(
                    "unauthorized",
                    "Authentication failed (401) even after token refresh. "
                    "Check your OAuth credentials.",
                    response,
                )
        else:
            if auth_manager and auth_manager.config.type.value == "api_key":
                hint = api_key_401_hint(method, url)
            else:
                hint = (
                    "New instances accept basic auth only for users with 'Web service "
                    "access only' or the snc_basic_auth_api_access role, admin included; "
                    "otherwise check the username and password. "
                    f"See {_TROUBLESHOOTING}#401-unauthorized."
                )
            raise refused(
                "unauthorized", f"Authentication failed (401). {hint}", response, hint
            )

    if response.status_code == 403:
        hint = (
            "The user may lack permissions for this API; "
            f"roles per tool: {_DOCS}/docs/tools.md#roles."
        )
        raise refused("forbidden", f"Access denied (403). {hint}", response, hint)
    if response.status_code == 404:
        hint = (
            "The table or record doesn't exist, or an ACL "
            "hides the record from this identity."
        )
        raise refused("not_found", f"Not found (404). {hint}", response, hint)

    # For other errors, raise with what ServiceNow said, never the raw body
    if not response.ok:
        raise failure(
            "http_error",
            f"HTTP {response.status_code} from {where}. {_error_context(response)}",
            response=response,
        )

    return response


def result_rows(data: Any) -> list:
    """The ``result`` of a Table API list call as a list of records.

    ServiceNow returns a list of objects. Anything else (a single object, null,
    stray scalars) is normalised so the list tools' published outputSchema
    still holds: one object becomes a one-row list, everything else is dropped.
    """
    result = data.get("result") if isinstance(data, dict) else None
    if isinstance(result, dict):
        return [result]
    if not isinstance(result, list):
        return []
    return [row for row in result if isinstance(row, dict)]


def parse_json_response(response: requests.Response, url: str) -> Dict[str, Any]:
    """Parse a JSON response, raising ServiceNowAPIError on failure."""
    where = error_target(url)
    if not response.text or not response.text.strip():
        raise _failure(
            "empty_body",
            f"Empty response body from {where} (HTTP {response.status_code}). "
            f"The instance may be hibernating: wake it at {_PDI_WAKE_URL}",
            url=url,
            response=response,
        )

    content_type = response.headers.get("Content-Type", "")
    if "text/html" in content_type:
        raise _failure(
            "html_body",
            f"Got HTML instead of JSON from {where}. That is a hibernating PDI or a "
            f"login page: wake the instance at {_PDI_WAKE_URL}, or check the "
            f"credentials. See {_TROUBLESHOOTING}#instance-is-hibernating",
            url=url,
            response=response,
        )

    try:
        return response.json()
    except ValueError:
        # The body is not quoted: a cut-off list of records still holds their
        # values. Not chained either: the parser's error keeps the whole body
        # in its ``doc``.
        raise _failure(
            "invalid_json",
            f"Invalid JSON from {where}. Response: {_body_summary(response)}",
            url=url,
            response=response,
        ) from None
