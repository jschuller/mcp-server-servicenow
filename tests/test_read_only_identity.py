"""Write tools disappear for a caller whose identity has snc_read_only."""

import json
from unittest.mock import Mock

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth.auth import AccessToken

from servicenow_mcp.middleware.audit import configure_audit_log
from servicenow_mcp.server import mcp
from servicenow_mcp.tools import table_tools
from tests.conftest import init_test_services, sn_response
from tests.inventory import ALL_TOOLS, READ_TOOLS

HAS_ROLE = "servicenow_mcp.middleware.read_only_identity.has_role"


def _lookup(monkeypatch, answer):
    calls = []

    def fake(*args):
        calls.append(args)
        return answer

    monkeypatch.setattr(HAS_ROLE, fake)
    return calls


async def _tool_names(server=mcp) -> set[str]:
    async with Client(server) as client:
        return {tool.name for tool in await client.list_tools()}


def _as_caller(monkeypatch, claims) -> None:
    token = AccessToken(token="t", client_id="c", scopes=[], claims=claims)
    monkeypatch.setattr("fastmcp.server.dependencies.get_access_token", lambda: token)


async def test_read_only_identity_lists_only_read_tools(monkeypatch) -> None:
    calls = _lookup(monkeypatch, True)
    init_test_services()

    names = await _tool_names()

    assert len(names) == len(READ_TOOLS)
    assert "create_record" not in names and "list_records" in names
    # One lookup, for the caller, with a short timeout.
    assert calls == [("https://test.service-now.com/api/now", 5, "snc_read_only")]


async def test_definite_answer_is_cached(monkeypatch) -> None:
    calls = _lookup(monkeypatch, True)
    init_test_services()
    await _tool_names()
    await _tool_names()
    assert len(calls) == 1


async def test_writable_identity_keeps_every_tool(monkeypatch) -> None:
    _lookup(monkeypatch, False)
    init_test_services()
    assert len(await _tool_names()) == len(ALL_TOOLS)


async def test_failed_lookup_fails_open_and_retries(monkeypatch) -> None:
    calls = _lookup(monkeypatch, None)
    init_test_services()
    assert len(await _tool_names()) == len(ALL_TOOLS)
    assert len(await _tool_names()) == len(ALL_TOOLS)
    assert len(calls) == 2  # an unknown answer is not cached


async def test_write_call_is_refused_before_servicenow(monkeypatch, tmp_path) -> None:
    _lookup(monkeypatch, True)
    sn = Mock(return_value=sn_response({"result": {"sys_id": "1"}}))
    monkeypatch.setattr(table_tools, "make_sn_request", sn)
    init_test_services()
    log = tmp_path / "audit.jsonl"
    configure_audit_log(str(log))

    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="snc_read_only; write tools are hidden"):
            await client.call_tool(
                "create_record", {"table_name": "incident", "data": {"x": "1"}}
            )
        await client.call_tool("list_records", {"table_name": "incident"})

    assert [c.args[0] for c in sn.call_args_list] == ["GET"]
    outcomes = [json.loads(line)["outcome"] for line in log.read_text().splitlines()]
    assert outcomes == ["denied", "ok"]


async def test_read_only_flag_needs_no_lookup(monkeypatch) -> None:
    calls = _lookup(monkeypatch, True)
    init_test_services(read_only=True)
    mcp.disable(tags={"write"}, components={"tool"})
    assert len(await _tool_names()) == len(READ_TOOLS)
    assert calls == []


async def test_oauth_caller_uses_the_token_claim(monkeypatch) -> None:
    calls = _lookup(monkeypatch, False)
    init_test_services()

    _as_caller(monkeypatch, {"user_name": "jane", "sn_read_only": True})
    assert len(await _tool_names()) == len(READ_TOOLS)
    _as_caller(monkeypatch, {"user_name": "joe", "sn_read_only": None})
    assert len(await _tool_names()) == len(ALL_TOOLS)
    assert calls == []  # per-user tokens never use the service-account lookup


async def test_static_token_caller_uses_the_service_account(monkeypatch) -> None:
    calls = _lookup(monkeypatch, True)
    init_test_services()
    _as_caller(monkeypatch, {"sn_auth": "service-account"})
    assert len(await _tool_names()) == len(READ_TOOLS)
    assert len(calls) == 1


async def test_hiding_survives_mount(monkeypatch) -> None:
    _lookup(monkeypatch, True)
    init_test_services()
    parent = FastMCP("orchestrator")
    parent.mount(mcp, namespace="snow")

    names = await _tool_names(parent)

    assert "snow_list_records" in names
    assert not any(n in names for n in ("snow_create_record", "snow_delete_record"))
    async with Client(parent) as client:
        with pytest.raises(ToolError, match="snc_read_only"):
            await client.call_tool(
                "snow_delete_record", {"table_name": "incident", "sys_id": "a"}
            )
