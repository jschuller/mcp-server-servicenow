"""AuditMiddleware: one JSON line per call, never values, never stdout."""

import json
import logging
from typing import Any, List
from unittest.mock import Mock

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from servicenow_mcp.middleware import audit
from servicenow_mcp.server import mcp
from servicenow_mcp.tools import table_tools
from tests.conftest import init_test_services, sn_response


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: List[dict[str, Any]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(json.loads(record.getMessage()))


@pytest.fixture
def captured(tmp_path) -> _Capture:
    audit.configure_audit_log(str(tmp_path / "audit.jsonl"))
    handler = _Capture()
    audit.logger.addHandler(handler)
    yield handler
    audit.logger.removeHandler(handler)


@pytest.fixture
def sn_mock(monkeypatch) -> Mock:
    mock = Mock(
        return_value=sn_response({"result": [{"sys_id": "1", "number": "INC1"}]})
    )
    monkeypatch.setattr(table_tools, "make_sn_request", mock)
    return mock


@pytest.mark.asyncio
async def test_ok_line_has_keys_not_values(
    captured: _Capture, sn_mock: Mock, capsys
) -> None:
    init_test_services()
    async with Client(mcp) as client:
        await client.call_tool(
            "list_records",
            {
                "table_name": "incident",
                "query": "active=true^user_password=hunter2",
                "limit": 5,
            },
        )
        sn_mock.return_value = sn_response({"result": {"sys_id": "1"}})
        await client.call_tool(
            "create_record",
            {"table_name": "incident", "data": {"short_description": "SECRET-VALUE"}},
        )
    assert [line["outcome"] for line in captured.lines] == ["ok", "ok"]
    first, second = captured.lines
    assert first["event"] == "tool_call" and first["name"] == "list_records"
    assert first["table"] == "incident" and first["limit"] == 5
    assert first["user"] == "admin" and first["auth_mode"] == "service-account"
    assert "hunter2" not in first["query"] and "[REDACTED]" in first["query"]
    assert "read" in first["tags"]
    assert second["data_keys"] == ["short_description"]
    assert "SECRET-VALUE" not in json.dumps(second)
    assert captured.lines[0]["run_id"] == audit.RUN_ID
    assert capsys.readouterr().out == ""


@pytest.mark.asyncio
async def test_error_denied_and_unknown_outcomes(
    captured: _Capture, sn_mock: Mock
) -> None:
    init_test_services()
    sn_mock.side_effect = RuntimeError("boom")
    async with Client(mcp) as client:
        with pytest.raises(ToolError):
            await client.call_tool("list_records", {"table_name": "incident"})
        with pytest.raises(ToolError):
            await client.call_tool("list_records", {"table_name": "incident^ORx"})
        with pytest.raises(ToolError):
            await client.call_tool("no_such_tool", {})
    outcomes = [line["outcome"] for line in captured.lines]
    assert outcomes == ["error", "denied", "unknown_tool"]
    assert (
        captured.lines[0]["error"].startswith("ToolError")
        or "boom" in captured.lines[0]["error"]
    )
    assert "Invalid table name" in captured.lines[1]["error"]


@pytest.mark.asyncio
async def test_resource_read_line(captured: _Capture, monkeypatch) -> None:
    init_test_services()
    monkeypatch.setattr(
        "servicenow_mcp.server.make_sn_request",
        Mock(return_value=sn_response({"result": []})),
    )
    async with Client(mcp) as client:
        await client.read_resource("servicenow://help/query-syntax")
        await client.read_resource("servicenow://schema/incident")
    assert captured.lines[0]["event"] == "resource_read"
    assert captured.lines[0]["name"] == "servicenow://help/query-syntax"
    assert captured.lines[1]["table"] == "incident"


@pytest.mark.asyncio
async def test_skill_resource_read_line(captured: _Capture) -> None:
    """Every skill load is audited; an unknown URI is labelled unknown_resource."""
    init_test_services()
    async with Client(mcp) as client:
        await client.read_resource("skill://triaging-incidents/SKILL.md")
        with pytest.raises(Exception):
            await client.read_resource("skill://no-such-skill/SKILL.md")
    assert captured.lines[0]["event"] == "resource_read"
    assert captured.lines[0]["name"] == "skill://triaging-incidents/SKILL.md"
    assert captured.lines[0].get("table") is None  # None fields are not emitted
    assert captured.lines[0]["outcome"] == "ok"
    assert captured.lines[1]["outcome"] == "unknown_resource"


def test_truncated_response_is_detected() -> None:
    """ResponseLimitingMiddleware returns (never raises) a suffixed result."""
    from fastmcp.tools.base import ToolResult
    from mcp.types import TextContent

    plain = ToolResult(content=[TextContent(type="text", text="{}")])
    cut = ToolResult(
        content=[TextContent(type="text", text="{...}" + audit.TRUNCATION_SUFFIX)]
    )
    assert audit._is_truncated(plain) is False
    assert audit._is_truncated(cut) is True


@pytest.mark.asyncio
async def test_off_emits_nothing(sn_mock: Mock) -> None:
    init_test_services()
    assert audit.configure_audit_log("off") is False
    handler = _Capture()
    audit.logger.addHandler(handler)
    try:
        async with Client(mcp) as client:
            await client.call_tool("list_records", {"table_name": "incident"})
    finally:
        audit.logger.removeHandler(handler)
    assert handler.lines == []


@pytest.mark.asyncio
async def test_file_target_writes_json_lines(tmp_path, sn_mock: Mock) -> None:
    init_test_services()
    path = tmp_path / "audit.jsonl"
    assert audit.configure_audit_log(str(path)) is True
    async with Client(mcp) as client:
        await client.call_tool("list_records", {"table_name": "incident"})
    audit.configure_audit_log("off")
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(lines) == 1 and lines[0]["name"] == "list_records"


def test_redact_query_masks_sensitive_values() -> None:
    q = "active=true^user_password=abc^api_keyLIKEsecret^nameSTARTSWITHbob"
    assert audit.redact_query(q) == (
        "active=true^user_password=[REDACTED]^api_keyLIKE[REDACTED]^nameSTARTSWITHbob"
    )
    assert len(audit.redact_query("a=" + "b" * 500)) <= audit.QUERY_MAX_CHARS + 1


def test_identity_for_static_and_oauth_tokens(monkeypatch) -> None:
    from fastmcp.server.auth.auth import AccessToken

    static = AccessToken(
        token="t",
        client_id="static-client-1",
        scopes=[],
        claims={"sn_auth": "service-account"},
    )
    monkeypatch.setattr("fastmcp.server.dependencies.get_access_token", lambda: static)
    assert audit._identity() == ("static-token", "static-client-1")
    user = AccessToken(
        token="t", client_id="c", scopes=[], claims={"user_name": "jane"}
    )
    monkeypatch.setattr("fastmcp.server.dependencies.get_access_token", lambda: user)
    assert audit._identity() == ("oauth", "jane")
