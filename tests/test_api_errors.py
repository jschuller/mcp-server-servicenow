"""A ServiceNow API failure: what the client reads, per transport, and what the log gets.

Over stdio the message keeps the instance URL and ServiceNow's diagnostic headers.
On every other transport it keeps the status, ServiceNow's own message, the API
path and the hints, and nothing that names the instance. No form carries a query
string or quotes a response body: only the message and detail of ServiceNow's JSON
error are shown. FastMCP logs no traceback for these failures; one WARNING line
carries the facts.
"""

from __future__ import annotations

import json
import logging
import socket
import sys
from contextlib import contextmanager
from typing import Any, Callable, Iterator, List, Optional
from unittest.mock import patch

import pytest
import requests
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StdioTransport
from fastmcp.exceptions import ToolError
from fastmcp.server.context import reset_transport, set_transport
from mcp import MCPError

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.middleware import audit
from servicenow_mcp.middleware.api_errors import LOG_PREFIX
from servicenow_mcp.server import mcp
from servicenow_mcp.utils.config import (
    ApiKeyConfig,
    AuthConfig,
    AuthType,
    BasicAuthConfig,
    OAuthConfig,
)
from servicenow_mcp.utils.http import (
    ServiceNowAPIError,
    api_request,
    local_error_detail,
    parse_json_response,
)
from tests.conftest import init_test_services

HOST = "instance.example"
BASE = f"https://{HOST}"
PATH = "/api/now/table/incident"
URL = BASE + PATH
# A filter value the caller sent: it must never come back in an error.
FILTER = "u_api_tokenSTARTSWITHfilter-value-9f3"
TXN = "txn0a1b2c3d4e5f"
SN_HEADERS = {"X-Is-Logged-In": "false", "X-Transaction-ID": TXN}
ROLES_LINK = (
    "https://github.com/jschuller/mcp-server-servicenow/blob/main/docs/tools.md#roles"
)
REQUEST = "servicenow_mcp.utils.http.requests.request"


def sn_error(message: str, detail: str) -> dict[str, Any]:
    return {"error": {"message": message, "detail": detail}, "status": "failure"}


NOT_AUTHENTICATED = sn_error(
    "User Not Authenticated", "Required to provide Auth information"
)
NOT_AUTHORIZED = sn_error("User Not Authorized", "Failed API level ACL Validation")
NO_RECORD = sn_error(
    "No Record found", "Record doesn't exist or ACL restricts the record retrieval"
)


def response(
    status: int,
    body: Any = "",
    content_type: str = "application/json",
    headers: Optional[dict[str, str]] = None,
) -> requests.Response:
    """A real requests.Response, so .ok, .text and .json() behave as in production."""
    reply = requests.Response()
    reply.status_code = status
    reply._content = (body if isinstance(body, str) else json.dumps(body)).encode()
    reply.encoding = "utf-8"
    reply.headers["Content-Type"] = content_type
    reply.headers.update(SN_HEADERS if headers is None else headers)
    return reply


def manager(kind: str) -> AuthManager:
    if kind == "api_key":
        config = AuthConfig(type=AuthType.API_KEY, api_key=ApiKeyConfig(api_key="k"))
    elif kind == "oauth":
        config = AuthConfig(
            type=AuthType.OAUTH,
            oauth=OAuthConfig(client_id="client", client_secret="not-a-real-secret"),
        )
    else:
        config = AuthConfig(
            type=AuthType.BASIC, basic=BasicAuthConfig(username="u", password="p")
        )
    auth = AuthManager(config, BASE)
    if kind == "oauth":
        auth.token, auth.token_type = "held-token", "Bearer"
    return auth


def network_error(cls: type[Exception], cause: str) -> Exception:
    """What requests raises: the host, the path and the query string, then the cause."""
    return cls(
        f"HTTPSConnectionPool(host='{HOST}', port=443): Max retries exceeded with "
        f"url: {PATH}?sysparm_query={FILTER}&sysparm_limit=10 (Caused by {cause})"
    )


def dns_error() -> Exception:
    try:
        try:
            raise socket.gaierror(8, "nodename nor servname provided, or not known")
        except socket.gaierror as dns:
            raise OSError(f"Failed to resolve '{HOST}'") from dns
    except OSError as reason:
        return requests.ConnectionError(reason)


def call(
    answer: Any, auth: str = "basic", *, bearer: Optional[str] = None
) -> ServiceNowAPIError:
    """The error api_request raises when ServiceNow answers (or fails) with ``answer``."""
    kwargs: dict[str, Any] = {"params": {"sysparm_query": FILTER}}
    if bearer:
        kwargs["bearer_token"] = bearer
    else:
        kwargs["auth_manager"] = manager(auth)
    side_effect = answer if isinstance(answer, (list, Exception)) else [answer, answer]
    with patch(REQUEST, side_effect=side_effect):
        with pytest.raises(ServiceNowAPIError) as raised:
            api_request("GET", URL, **kwargs)
    return raised.value


def call_both(answer: Callable[[], Any], auth: str = "basic", **kwargs: Any) -> tuple:
    """(local error, remote error) for the same failure."""
    with local_error_detail():
        local = call(answer(), auth, **kwargs)
    return local, call(answer(), auth, **kwargs)


def assert_trimmed(error: ServiceNowAPIError) -> str:
    """The remote form: nothing that names the instance, no headers, no raw body."""
    text = str(error)
    for leak in (HOST, "https://instance", TXN, "X-Is-Logged-In", "Headers:", FILTER):
        assert leak not in text, leak
    assert '{"error"' not in text and "sysparm_query" not in text
    return text


def assert_no_query_anywhere(error: ServiceNowAPIError) -> None:
    carried = str(error) + json.dumps([error.details, error.diagnostics])
    assert FILTER not in carried and "sysparm_query" not in carried


# --- ServiceNow answered: 401 variants, 403, 404, 5xx ------------------------


def test_403_text_local_and_remote() -> None:
    local, remote = call_both(lambda: response(403, NOT_AUTHORIZED))
    head = (
        "Access denied (403). The user may lack permissions for this API; "
        f"roles per tool: {ROLES_LINK}. "
    )
    assert str(local) == (
        head + f"URL: {URL} | ServiceNow error: User Not Authorized: "
        "Failed API level ACL Validation | "
        f"Headers: {{'X-Is-Logged-In': 'false', 'X-Transaction-ID': '{TXN}'}}"
    )
    assert assert_trimmed(remote) == (
        head + f"URL: {PATH} | ServiceNow error: User Not Authorized: "
        "Failed API level ACL Validation"
    )
    for error in (local, remote):
        assert error.status == 403
        assert error.details == {
            "kind": "forbidden",
            "status": 403,
            "method": "GET",
            "path": PATH,
            "sn_message": "User Not Authorized",
            "sn_detail": "Failed API level ACL Validation",
            "hint": "The user may lack permissions for this API; "
            f"roles per tool: {ROLES_LINK}.",
        }
        assert error.diagnostics == {"headers": SN_HEADERS}
        assert_no_query_anywhere(error)


def test_401_basic_text_local_and_remote() -> None:
    local, remote = call_both(lambda: response(401, NOT_AUTHENTICATED))
    head = (
        "Authentication failed (401). New instances accept basic auth only for users "
        "with 'Web service access only' or the snc_basic_auth_api_access role, admin "
        "included; otherwise check the username and password. See "
        "https://github.com/jschuller/mcp-server-servicenow/blob/main/"
        "TROUBLESHOOTING.md#401-unauthorized. "
    )
    assert str(local).startswith(
        head + f"URL: {URL} | ServiceNow error: User Not Authenticated: "
        "Required to provide Auth information | Headers: {"
    )
    assert f"'X-Transaction-ID': '{TXN}'" in str(local)
    assert assert_trimmed(remote) == (
        head + f"URL: {PATH} | ServiceNow error: User Not Authenticated: "
        "Required to provide Auth information"
    )
    assert local.status == remote.status == 401
    assert remote.details["kind"] == "unauthorized"
    assert "snc_basic_auth_api_access" in remote.details["hint"]


def test_401_api_key_keeps_the_access_policy_hint() -> None:
    local, remote = call_both(lambda: response(401, NOT_AUTHENTICATED), "api_key")
    for error in (local, remote):
        assert error.status == 401
        assert "REST API access policy maps it for this API and method (GET)" in str(
            error
        )
    assert URL in str(local)
    assert f"URL: {PATH} | ServiceNow error: User Not Authenticated" in assert_trimmed(
        remote
    )


def test_401_bearer_token() -> None:
    local, remote = call_both(
        lambda: response(401, NOT_AUTHENTICATED), bearer="caller-token-value"
    )
    for error in (local, remote):
        assert error.status == 401
        assert str(error).startswith(
            "Authentication failed (401) for the bearer-token request. The token may "
            "be expired or not valid for this instance. URL: "
        )
        assert "caller-token-value" not in str(error) + json.dumps(
            [error.details, error.diagnostics]
        )
    assert URL in str(local)
    assert_trimmed(remote)


def test_401_oauth_after_a_refresh() -> None:
    def errors() -> ServiceNowAPIError:
        with patch.object(AuthManager, "refresh_token"):
            return call(response(401, NOT_AUTHENTICATED), "oauth")

    with local_error_detail():
        local = errors()
    remote = errors()
    for error in (local, remote):
        assert error.status == 401 and error.details["kind"] == "unauthorized"
        assert "Authentication failed (401) even after token refresh" in str(error)
    assert URL in str(local)
    assert assert_trimmed(remote).endswith(
        f"URL: {PATH} | ServiceNow error: User Not Authenticated: "
        "Required to provide Auth information"
    )


def test_401_oauth_refresh_failed_keeps_the_marker_callers_match() -> None:
    """find_references stops on "token refresh also failed": a refused secret."""
    refusal = ValueError(
        f"Failed to get OAuth token: 401 <html>{BASE}/oauth_token.do "
        f"?sysparm_query={FILTER}</html>"
    )

    def errors() -> ServiceNowAPIError:
        with patch.object(AuthManager, "refresh_token", side_effect=refusal):
            return call(response(401, NOT_AUTHENTICATED), "oauth")

    with local_error_detail():
        local = errors()
    remote = errors()
    assert str(local).startswith(
        "Authentication failed (401) and token refresh also failed. "
        f"URL: {URL}. Refresh error: Failed to get OAuth token: 401"
    )
    assert assert_trimmed(remote) == (
        f"Authentication failed (401) and token refresh also failed. URL: {PATH}."
    )
    for error in (local, remote):
        assert error.status == 401 and error.details["kind"] == "token_refresh"
        assert "Failed to get OAuth token" in error.diagnostics["cause"]
        assert_no_query_anywhere(error)


def test_404_text_local_and_remote() -> None:
    local, remote = call_both(lambda: response(404, NO_RECORD))
    head = (
        "Not found (404). The table or record doesn't exist, or an ACL hides the "
        "record from this identity. "
    )
    assert str(local).startswith(
        head + f"URL: {URL} | ServiceNow error: No Record found: "
    )
    assert assert_trimmed(remote) == (
        head + f"URL: {PATH} | ServiceNow error: No Record found: "
        "Record doesn't exist or ACL restricts the record retrieval"
    )
    assert local.status == remote.status == 404
    assert remote.details["kind"] == "not_found"


def test_5xx_with_servicenow_json() -> None:
    body = sn_error("Transaction cancelled: maximum execution time exceeded", "")
    local, remote = call_both(lambda: response(500, body))
    said = "ServiceNow error: Transaction cancelled: maximum execution time exceeded"
    assert str(local).startswith(f"HTTP 500 from {URL}. {said} | Headers: {{")
    assert assert_trimmed(remote) == f"HTTP 500 from {PATH}. {said}"
    assert local.status == remote.status == 500
    assert remote.details["kind"] == "http_error"


def test_5xx_html_page_is_described_not_quoted() -> None:
    """A proxy's or the instance's HTML error page can name hosts and hold values."""
    page = f"<html><body>Bad gateway: upstream {HOST} at gw-7.internal</body></html>"
    local, remote = call_both(lambda: response(502, page, "text/html; charset=utf-8"))
    said = f"Response: text/html, {len(page)} characters, not JSON, not shown"
    assert str(local).startswith(f"HTTP 502 from {URL}. {said} | Headers: {{")
    assert assert_trimmed(remote) == f"HTTP 502 from {PATH}. {said}"
    for error in (local, remote):
        assert "gw-7.internal" not in str(error)
        # The log line says what the body was, not what it said.
        assert error.diagnostics["body"] == said.removeprefix("Response: ")


def test_5xx_empty_body() -> None:
    local, remote = call_both(lambda: response(503, ""))
    assert str(local).startswith(
        f"HTTP 503 from {URL}. Response: (empty) | Headers: {{"
    )
    assert assert_trimmed(remote) == f"HTTP 503 from {PATH}. Response: (empty)"
    assert "body" not in remote.diagnostics


def test_servicenow_text_that_names_the_instance_is_masked_remotely() -> None:
    body = sn_error("Blocked", f"See {BASE}/nav_to.do for the policy")
    local, remote = call_both(lambda: response(403, body))
    assert HOST in str(local)
    assert assert_trimmed(remote).endswith(
        "ServiceNow error: Blocked: See https://<instance>/nav_to.do for the policy"
    )


def test_long_servicenow_text_is_bounded() -> None:
    _, remote = call_both(lambda: response(403, sn_error("m" * 5000, "d" * 5000)))
    assert len(remote.details["sn_message"]) == len(remote.details["sn_detail"]) == 301
    assert len(str(remote)) < 1000


# --- ServiceNow never answered: timeout, DNS, TLS, refused, other -------------


def test_timeout() -> None:
    local, remote = call_both(
        lambda: network_error(requests.Timeout, "ReadTimeoutError('timed out')")
    )
    tail = " timed out after 30s. The instance may be hibernating or overloaded."
    assert str(local) == f"Request to {URL}" + tail
    assert assert_trimmed(remote) == f"Request to {PATH}" + tail
    for error in (local, remote):
        assert error.status is None and error.details["kind"] == "timeout"
        assert "status" not in error.details
        assert_no_query_anywhere(error)


def test_dns() -> None:
    local, remote = call_both(dns_error)
    assert str(local).startswith(f"Cannot resolve the host in {URL}. Check the")
    assert f"Detail: Failed to resolve '{HOST}'" in str(local)
    text = assert_trimmed(remote)
    assert text.startswith(
        f"Cannot resolve the host in the instance URL (request to {PATH}). Check the"
    )
    assert text.endswith("TROUBLESHOOTING.md#instance-not-found.")
    assert remote.status is None and remote.details["kind"] == "dns"
    assert HOST in remote.diagnostics["cause"]  # the operator's log names it


def test_tls() -> None:
    local, remote = call_both(
        lambda: network_error(
            requests.exceptions.SSLError,
            "SSLCertVerificationError('certificate verify failed')",
        )
    )
    for error in (local, remote):
        assert "REQUESTS_CA_BUNDLE" in str(error)
        assert "TROUBLESHOOTING.md#certificate-verify-failed." in str(error)
        assert error.status is None and error.details["kind"] == "tls"
        assert_no_query_anywhere(error)
    assert str(local).startswith(f"TLS certificate check failed for {URL}. ")
    assert "Detail: HTTPSConnectionPool" in str(local)
    assert "certificate verify failed" in str(local)
    text = assert_trimmed(remote)
    assert text.startswith(f"TLS certificate check failed for {PATH}. ")
    assert "Detail:" not in text


def test_connection_refused() -> None:
    local, remote = call_both(
        lambda: network_error(
            requests.ConnectionError, "ConnectionRefusedError(61, 'refused')"
        )
    )
    assert str(local).startswith(f"Cannot connect to ServiceNow at {URL}. ")
    assert "Detail: HTTPSConnectionPool" in str(local)
    assert assert_trimmed(remote) == (
        f"Cannot connect to ServiceNow at {PATH}. Check that the instance URL is "
        "correct and the instance is awake."
    )
    for error in (local, remote):
        assert error.details["kind"] == "connection"
        assert_no_query_anywhere(error)


def test_any_other_requests_failure_is_an_api_error_too() -> None:
    """Too many redirects and the like used to escape as a raw requests error."""
    local, remote = call_both(
        lambda: requests.TooManyRedirects(f"Exceeded 30 redirects for {URL}")
    )
    assert str(local) == (
        f"Request to {URL} failed (TooManyRedirects). "
        f"Detail: Exceeded 30 redirects for {URL}"
    )
    assert assert_trimmed(remote) == f"Request to {PATH} failed (TooManyRedirects)."


def test_retry_after_a_refresh_that_gets_no_answer() -> None:
    def errors() -> ServiceNowAPIError:
        with patch.object(AuthManager, "refresh_token"):
            return call(
                [
                    response(401, NOT_AUTHENTICATED),
                    network_error(requests.ConnectionError, "reset"),
                ],
                "oauth",
            )

    with local_error_detail():
        local = errors()
    remote = errors()
    assert str(local).startswith(
        "Retry after token refresh failed: HTTPSConnectionPool"
    )
    assert assert_trimmed(remote) == (
        "Retry after token refresh failed: the instance did not answer "
        "(ConnectionError)."
    )
    assert_no_query_anywhere(local)


@pytest.mark.parametrize(
    ("failure", "kind", "local_start", "remote_text"),
    [
        (
            requests.ConnectionError(f"HTTPSConnectionPool(host='{HOST}'): refused"),
            "connection",
            "Cannot connect to ServiceNow to get an OAuth token.",
            "Cannot connect to ServiceNow to get an OAuth token. Check that the "
            "instance URL is correct and the instance is awake.",
        ),
        (
            ValueError(f"Failed to get OAuth token: 401 <html>{HOST}</html>"),
            "token_request",
            "Failed to get OAuth token: 401",
            "Could not get an OAuth token for the ServiceNow identity this server "
            "uses; the server's log has the token endpoint's answer.",
        ),
    ],
)
def test_first_oauth_token_failure(
    failure: Exception, kind: str, local_start: str, remote_text: str
) -> None:
    """The first token is requested inside api_request: no raw error escapes it."""

    def error() -> ServiceNowAPIError:
        with patch.object(AuthManager, "get_headers", side_effect=failure):
            with pytest.raises(ServiceNowAPIError) as raised:
                api_request("GET", URL, manager("oauth"))
        return raised.value

    with local_error_detail():
        local = error()
    remote = error()
    assert str(local).startswith(local_start) and HOST in str(local)
    assert assert_trimmed(remote) == remote_text
    assert remote.details["kind"] == kind and HOST in remote.diagnostics["cause"]


# --- a 200 that is not JSON ----------------------------------------------------


@pytest.mark.parametrize(
    ("reply", "kind", "start"),
    [
        (
            response(200, ""),
            "empty_body",
            "Empty response body from {where} (HTTP 200).",
        ),
        (
            response(200, f"<html>{HOST} is hibernating</html>", "text/html"),
            "html_body",
            "Got HTML instead of JSON from {where}. That is a hibernating PDI",
        ),
        (
            response(200, f"{{not json at {HOST}"),
            "invalid_json",
            "Invalid JSON from {where}: ",
        ),
    ],
)
def test_parse_json_response(reply: requests.Response, kind: str, start: str) -> None:
    with local_error_detail():
        with pytest.raises(ServiceNowAPIError) as local:
            parse_json_response(reply, URL)
    with pytest.raises(ServiceNowAPIError) as remote:
        parse_json_response(reply, URL)
    assert str(local.value).startswith(start.format(where=URL))
    assert assert_trimmed(remote.value).startswith(start.format(where=PATH))
    assert remote.value.details["kind"] == kind
    for raised in (local.value, remote.value):
        assert "Response starts with" not in str(raised)
        if kind == "invalid_json":
            assert str(raised).endswith(
                f". Response: application/json, {len(reply.text)} characters, "
                "not JSON, not shown"
            )


# --- a response body is never quoted: it can hold a record's values -----------

# Stands for a credential held in a record field, a system property's value say.
CANARY = "canary-7Qm2-value-of-a-password-property"
ROWS = {"result": [{"name": "glide.example.password", "value": CANARY}]}
LEAKY_BODIES = {
    "a 200 cut off mid-record": (200, json.dumps(ROWS)[:-12], "application/json"),
    "a 200 that is an HTML page": (200, f"<html>{CANARY}</html>", "text/html"),
    "a 200 of plain text": (200, f"value={CANARY}", "text/plain"),
    "a 500 with rows, not an error": (500, ROWS, "application/json"),
    "a 500 cut off mid-record": (500, json.dumps(ROWS)[:-12], "application/json"),
    "a 500 JSON list": (500, [CANARY], "application/json"),
    "a 403 HTML page": (403, f"<html>{CANARY}</html>", "text/html"),
    "a 401 of plain text": (401, f"denied {CANARY}", "text/plain"),
    "a 404 whose error is a string": (404, {"error": CANARY}, "application/json"),
    "a 403 error object with extra keys": (
        403,
        {"error": {"message": "m", "detail": "d", "value": CANARY}, **ROWS},
        "application/json",
    ),
    "a 400 whose message is not a string": (
        400,
        {"error": {"message": {"value": CANARY}, "detail": [CANARY]}},
        "application/json",
    ),
}


def _everything(error: BaseException) -> str:
    """All the text an error carries: its message, its data, its causes."""
    seen, texts = set(), []
    current: Optional[BaseException] = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        texts += [str(current), repr(current.args)]
        texts.append(json.dumps(getattr(current, "details", {}), default=str))
        texts.append(json.dumps(getattr(current, "diagnostics", {}), default=str))
        current = current.__cause__ or current.__context__
    return "\n".join(texts)


@pytest.mark.parametrize("local", [True, False], ids=["local", "remote"])
@pytest.mark.parametrize("body", LEAKY_BODIES.values(), ids=LEAKY_BODIES.keys())
def test_no_error_quotes_a_response_body(body: tuple, local: bool) -> None:
    status, content, content_type = body

    def fetch() -> None:
        with patch(REQUEST, return_value=response(status, content, content_type)):
            reply = api_request("GET", URL, manager("basic"))
        parse_json_response(reply, URL)

    with pytest.raises(ServiceNowAPIError) as raised:
        if local:
            with local_error_detail():
                fetch()
        else:
            fetch()
    assert CANARY not in _everything(raised.value)
    assert "glide.example.password" not in _everything(raised.value)
    assert ("https://" + HOST in str(raised.value)) is local  # the mode did apply


# --- through the server: tool results, resource reads, the log ----------------


@contextmanager
def over(transport: Optional[str]) -> Iterator[None]:
    """Run the block as a request FastMCP received over ``transport``."""
    if transport is None:  # an in-process client: FastMCP names no transport
        yield
        return
    token = set_transport(transport)  # type: ignore[arg-type]
    try:
        yield
    finally:
        reset_transport(token)


class _Records(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: List[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def logged() -> Iterator[_Records]:
    """Every record this server and FastMCP log (FastMCP's logger does not propagate)."""
    handler = _Records()
    loggers = [logging.getLogger("fastmcp"), logging.getLogger("servicenow_mcp")]
    for logger in loggers:
        logger.addHandler(handler)
    yield handler
    for logger in loggers:
        logger.removeHandler(handler)


@pytest.fixture
def served() -> None:
    init_test_services(instance_url=BASE)


LIST_INCIDENTS = ("list_records", {"table_name": "incident", "query": FILTER})
LOCAL_403 = (
    "Access denied (403). The user may lack permissions for this API; "
    f"roles per tool: {ROLES_LINK}. URL: {URL} | "
    "ServiceNow error: User Not Authorized: Failed API level ACL Validation | "
    f"Headers: {{'X-Is-Logged-In': 'false', 'X-Transaction-ID': '{TXN}'}}"
)
REMOTE_403 = (
    "Access denied (403). The user may lack permissions for this API; "
    f"roles per tool: {ROLES_LINK}. URL: {PATH} | "
    "ServiceNow error: User Not Authorized: Failed API level ACL Validation"
)


@pytest.mark.parametrize(
    ("transport", "expected"),
    [
        ("stdio", LOCAL_403),
        ("streamable-http", REMOTE_403),
        ("sse", REMOTE_403),
        (None, REMOTE_403),
    ],
)
async def test_tool_failure_is_a_tool_error_with_the_message_as_it_is(
    served: None, transport: Optional[str], expected: str
) -> None:
    with over(transport), patch(REQUEST, return_value=response(403, NOT_AUTHORIZED)):
        async with Client(mcp) as client:
            result = await client.call_tool(*LIST_INCIDENTS, raise_on_error=False)
            with pytest.raises(ToolError) as raised:
                await client.call_tool(*LIST_INCIDENTS)
    assert result.is_error is True
    assert result.structured_content is None
    assert [block.text for block in result.content] == [expected]
    assert str(raised.value) == expected


@pytest.mark.parametrize(
    ("transport", "where"), [("stdio", URL), ("streamable-http", PATH)]
)
async def test_401_through_a_tool(served: None, transport: str, where: str) -> None:
    with over(transport), patch(REQUEST, return_value=response(401, NOT_AUTHENTICATED)):
        async with Client(mcp) as client:
            result = await client.call_tool(*LIST_INCIDENTS, raise_on_error=False)
    text = result.content[0].text
    assert result.is_error is True
    assert text.startswith("Authentication failed (401). New instances accept basic")
    assert f"TROUBLESHOOTING.md#401-unauthorized. URL: {where} | " in text
    assert FILTER not in text and "Error calling tool" not in text
    assert (HOST in text) is (transport == "stdio")
    assert (TXN in text) is (transport == "stdio")


@pytest.mark.parametrize(
    ("transport", "expected"),
    [("stdio", LOCAL_403), ("streamable-http", REMOTE_403), (None, REMOTE_403)],
)
async def test_resource_read_fails_with_the_same_message(
    served: None, transport: Optional[str], expected: str
) -> None:
    table = "/api/now/table/sys_user_preference"
    with over(transport), patch(REQUEST, return_value=response(403, NOT_AUTHORIZED)):
        async with Client(mcp) as client:
            with pytest.raises(MCPError) as raised:
                await client.read_resource("servicenow://update-set/current")
    assert str(raised.value) == expected.replace(PATH, table)


async def test_a_server_launched_over_stdio_gives_the_local_detail(tmp_path) -> None:
    """The real transport, as a client starts it: FastMCP itself names it stdio.

    The instance is a closed local port, so nothing leaves this machine.
    """
    closed = "https://127.0.0.1:1"
    transport = StdioTransport(
        command=sys.executable,
        args=[
            *("-m", "servicenow_mcp.cli", "--transport", "stdio"),
            *("--instance-url", closed, "--auth-type", "basic"),
            *("--username", "u", "--password", "p", "--audit-log", "off"),
        ],
        cwd=str(tmp_path),
    )
    async with Client(transport) as client:
        result = await client.call_tool(*LIST_INCIDENTS, raise_on_error=False)
        with pytest.raises(MCPError) as raised:
            await client.read_resource("servicenow://update-set/current")
    text = result.content[0].text
    assert result.is_error is True
    assert f" {closed}{PATH}. " in text and "Error calling tool" not in text
    assert f" {closed}/api/now/table/sys_user_preference. " in str(raised.value)
    assert FILTER not in text and "sysparm_query" not in text


def _warnings(logged: _Records) -> List[dict[str, Any]]:
    return [
        json.loads(record.getMessage().removeprefix(LOG_PREFIX))
        for record in logged.records
        if record.name == "servicenow_mcp.middleware.api_errors"
        and record.levelno == logging.WARNING
    ]


@pytest.mark.parametrize("transport", ["stdio", "streamable-http"])
async def test_expected_failures_log_one_warning_each_and_no_traceback(
    served: None, logged: _Records, capfd, transport: str
) -> None:
    with over(transport), patch(REQUEST, return_value=response(403, NOT_AUTHORIZED)):
        async with Client(mcp) as client:
            await client.call_tool(*LIST_INCIDENTS, raise_on_error=False)
            with pytest.raises(MCPError):
                await client.read_resource("servicenow://update-set/current")

    assert [r for r in logged.records if r.levelno >= logging.ERROR] == []
    assert [r for r in logged.records if r.exc_info] == []
    assert "Traceback" not in capfd.readouterr().err
    fact = {
        "kind": "forbidden",
        "status": 403,
        "method": "GET",
        "sn_message": "User Not Authorized",
        "sn_detail": "Failed API level ACL Validation",
        "headers": SN_HEADERS,
    }
    assert _warnings(logged) == [
        {"event": "tool_call", "name": "list_records", "path": PATH, **fact},
        {
            "event": "resource_read",
            "name": "servicenow://update-set/current",
            "path": "/api/now/table/sys_user_preference",
            **fact,
        },
    ]
    assert FILTER not in "".join(record.getMessage() for record in logged.records)


@pytest.mark.parametrize("transport", ["stdio", "streamable-http"])
@pytest.mark.parametrize(
    "body",
    [
        LEAKY_BODIES[name]
        for name in (
            "a 200 cut off mid-record",
            "a 200 that is an HTML page",
            "a 500 with rows, not an error",
            "a 403 HTML page",
        )
    ],
    ids=["cut-off 200", "html 200", "500 rows", "403 html"],
)
async def test_a_body_reaches_no_result_log_record_or_audit_line(
    served: None, logged: _Records, capfd, tmp_path, body: tuple, transport: str
) -> None:
    """A system property's value in a body the server could not use stays there."""
    status, content, content_type = body
    log = tmp_path / "audit.jsonl"
    audit.configure_audit_log(str(log), transport=transport)
    calls = [
        ("get_system_properties", {"query": "nameLIKEpassword"}),
        ("list_records", {"table_name": "sys_properties"}),
        ("get_record", {"table_name": "sys_properties", "sys_id": "a" * 32}),
    ]
    seen: List[str] = []
    with (
        over(transport),
        patch(REQUEST, return_value=response(status, content, content_type)),
    ):
        async with Client(mcp) as client:
            for name, arguments in calls:
                result = await client.call_tool(name, arguments, raise_on_error=False)
                assert result.is_error is True, name
                seen += [block.text for block in result.content]
                seen.append(json.dumps(result.structured_content))
            # This resource reports what it could not read instead of failing.
            for content_block in await client.read_resource("servicenow://instance"):
                seen.append(content_block.text)
            with pytest.raises(MCPError) as raised:
                await client.read_resource("servicenow://update-set/current")
            seen.append(str(raised.value))

    formatter = logging.Formatter()
    records = [formatter.format(record) for record in logged.records]
    captured = capfd.readouterr()
    audit_lines = log.read_text()
    assert len(_warnings(logged)) == len(calls) + 1  # the logs were written
    assert audit_lines.count('"outcome":"error"') == len(calls) + 1
    for where in (*seen, *records, audit_lines, captured.err, captured.out):
        assert CANARY not in where


async def test_an_unexpected_exception_still_logs_its_traceback(
    served: None, logged: _Records
) -> None:
    """The control for the test above: a bug in a tool is still an ERROR with a traceback."""
    with patch(REQUEST, side_effect=RuntimeError("a bug")):
        async with Client(mcp) as client:
            result = await client.call_tool(*LIST_INCIDENTS, raise_on_error=False)
    assert result.content[0].text == "Error calling tool 'list_records': a bug"
    errors = [r for r in logged.records if r.levelno >= logging.ERROR]
    assert [(r.name, bool(r.exc_info)) for r in errors] == [
        ("fastmcp.server.server", True)
    ]
    assert _warnings(logged) == []


async def test_a_message_only_error_is_logged_with_its_message(
    served: None, logged: _Records
) -> None:
    """Read-only mode refuses a write before any request: there is no status to log."""
    init_test_services(instance_url=BASE, read_only=True)
    with over("streamable-http"):
        async with Client(mcp) as client:
            result = await client.call_tool(
                "create_record",
                {"table_name": "incident", "data": {"short_description": "x"}},
                raise_on_error=False,
            )
    assert result.is_error is True
    assert result.content[0].text == (
        f"Server is in read-only mode (--read-only); refusing POST {PATH}"
    )
    assert _warnings(logged) == [
        {
            "event": "tool_call",
            "name": "create_record",
            "kind": "read_only",
            "method": "POST",
        }
    ]


async def test_audit_line_names_the_error_class(served: None, tmp_path) -> None:
    log = tmp_path / "audit.jsonl"
    audit.configure_audit_log(str(log), transport="streamable-http")
    with (
        over("streamable-http"),
        patch(REQUEST, return_value=response(403, NOT_AUTHORIZED)),
    ):
        async with Client(mcp) as client:
            await client.call_tool(*LIST_INCIDENTS, raise_on_error=False)
    (line,) = [json.loads(text) for text in log.read_text().splitlines()]
    assert line["outcome"] == "error"
    assert line["error"].startswith("ServiceNowAPIError: Access denied (403). ")
    assert HOST not in line["error"]


async def test_mounted_server_trims_and_logs_the_same(
    served: None, logged: _Records
) -> None:
    parent = FastMCP("orchestrator")
    parent.mount(mcp, namespace="snow")
    with (
        over("streamable-http"),
        patch(REQUEST, return_value=response(403, NOT_AUTHORIZED)),
    ):
        async with Client(parent) as client:
            result = await client.call_tool(
                "snow_list_records", LIST_INCIDENTS[1], raise_on_error=False
            )
    assert result.is_error is True
    assert result.content[0].text == REMOTE_403
    assert [w["name"] for w in _warnings(logged)] == ["list_records"]
    assert [r for r in logged.records if r.exc_info] == []


# --- the callers that read the error ------------------------------------------


@pytest.mark.parametrize("transport", ["stdio", "streamable-http"])
async def test_find_references_still_tells_a_gap_from_a_failed_login(
    served: None, transport: str
) -> None:
    """Its 401/403 handling reads the message's first sentence in both forms."""

    def answer(method: str, url: str, **kwargs: Any) -> requests.Response:
        if url.endswith("/sys_security_acl"):
            return response(403, NOT_AUTHORIZED)
        return response(200, {"result": [{"sys_id": "1", "name": "n"}]})

    with over(transport), patch(REQUEST, side_effect=answer):
        async with Client(mcp) as client:
            report = (
                await client.call_tool("find_references", {"table_name": "incident"})
            ).structured_content
            assert report["not_assessable"] == [
                {
                    "source": "acls",
                    "table": "sys_security_acl",
                    "reason": "Access denied (403)",
                }
            ]
            assert len(report["groups"]) == 5

            # Basic auth: the first 401 is the password being refused. One request.
            with patch(
                REQUEST, return_value=response(401, NOT_AUTHENTICATED)
            ) as refused:
                result = await client.call_tool(
                    "find_references", {"table_name": "incident"}, raise_on_error=False
                )
            assert result.is_error is True and refused.call_count == 1
            assert result.content[0].text.startswith("Authentication failed (401). ")


@pytest.mark.parametrize("transport", ["stdio", "streamable-http"])
async def test_find_references_stops_when_the_oauth_refresh_fails(
    transport: str,
) -> None:
    init_test_services(
        instance_url=BASE,
        auth=AuthConfig(
            type=AuthType.OAUTH,
            oauth=OAuthConfig(client_id="client", client_secret="not-a-real-secret"),
        ),
    )
    from servicenow_mcp.server import get_auth_manager

    get_auth_manager().token = "held-token"
    with (
        over(transport),
        patch(REQUEST, return_value=response(401, NOT_AUTHENTICATED)) as request,
        patch.object(AuthManager, "refresh_token", side_effect=ValueError("refused")),
    ):
        async with Client(mcp) as client:
            result = await client.call_tool(
                "find_references", {"table_name": "incident"}, raise_on_error=False
            )
    assert result.is_error is True and request.call_count == 1
    assert "token refresh also failed" in result.content[0].text


@pytest.mark.parametrize(
    ("transport", "where"), [("stdio", BASE), ("streamable-http", "")]
)
async def test_schema_403_keeps_the_role_hint_and_the_facts(
    served: None, logged: _Records, transport: str, where: str
) -> None:
    with over(transport), patch(REQUEST, return_value=response(403, NOT_AUTHORIZED)):
        async with Client(mcp) as client:
            result = await client.call_tool(
                "get_table_schema",
                {"table_name": "incident", "include_inherited": False},
                raise_on_error=False,
            )
    text = result.content[0].text
    assert text.startswith("Access denied (403). ")
    assert f"URL: {where}/api/now/table/sys_dictionary | " in text
    assert text.endswith(
        " | Hint: reading table schemas (sys_dictionary) needs the "
        "personalize_dictionary role"
    )
    (warning,) = _warnings(logged)
    assert warning["status"] == 403 and warning["kind"] == "forbidden"
    assert warning["path"] == "/api/now/table/sys_dictionary"


def test_check_reads_as_local(capsys) -> None:
    """--check runs where the instance URL was typed: its lines keep the detail."""
    from servicenow_mcp.doctor import run_doctor

    config = init_test_services(instance_url=BASE)
    with patch(REQUEST, side_effect=dns_error()):
        code = run_doctor(config)
    out = capsys.readouterr().out
    assert code == 1 and "FAIL reach" in out
    assert f"Cannot resolve the host in {BASE}/api/now/table/sys_user. " in out


def test_an_error_raised_with_a_message_only_has_no_facts() -> None:
    error = ServiceNowAPIError("Cannot set the current update set")
    assert isinstance(error, ToolError)
    assert (error.status, error.details, error.diagnostics) == (None, {}, {})
    assert error.log_level == logging.DEBUG
