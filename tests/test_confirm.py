"""Opt-in destructive-call confirmation across both protocol eras."""

import json
from typing import Any, List
from unittest.mock import Mock

import pytest
from fastmcp import Client
from fastmcp.client.elicitation import ElicitResult
from fastmcp.exceptions import ToolError

from servicenow_mcp.server import mcp
from tests.conftest import init_test_services, sn_response

RECORD = {"sys_id": "abc123", "number": "INC0010001", "state": "2"}


@pytest.fixture
def sn_mock(monkeypatch) -> Mock:
    """Patch the server-level request used by the async write tools."""
    calls: List[tuple] = []

    def fake(method, url, timeout=30, params=None, json_data=None):
        calls.append((method, url, params, json_data))
        return sn_response({"result": RECORD})

    mock = Mock(side_effect=fake)
    mock.calls = calls
    monkeypatch.setattr("servicenow_mcp.server.make_sn_request", mock)
    return mock


def _methods(mock: Mock) -> List[str]:
    return [c[0] for c in mock.calls]


async def _accept(message, response_type, params, context):
    return True


async def _decline(message, response_type, params, context):
    return ElicitResult(action="decline")


async def _cancel(message, response_type, params, context):
    return ElicitResult(action="cancel")


UPDATE_ARGS = {"table_name": "incident", "sys_id": "abc123", "data": {"state": "6"}}


class TestDefaultOff:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("mode", ["auto", "legacy"])
    async def test_no_prompt_no_preview_single_call(
        self, sn_mock: Mock, mode: str
    ) -> None:
        init_test_services()
        prompts: List[str] = []

        async def handler(message, response_type, params, context):
            prompts.append(message)
            return True

        async with Client(mcp, mode=mode, elicitation_handler=handler) as client:
            result = await client.call_tool("update_record", UPDATE_ARGS)
            deleted = await client.call_tool(
                "delete_record", {"table_name": "incident", "sys_id": "abc123"}
            )
        assert prompts == []
        assert _methods(sn_mock) == ["PATCH", "DELETE"]
        assert result.data["sys_id"] == "abc123"
        assert deleted.data == {
            "deleted": True,
            "table": "incident",
            "sys_id": "abc123",
        }

    @pytest.mark.asyncio
    async def test_confirm_arg_is_inert(self, sn_mock: Mock) -> None:
        init_test_services()
        async with Client(mcp) as client:
            await client.call_tool("update_record", {**UPDATE_ARGS, "confirm": True})
        assert _methods(sn_mock) == ["PATCH"]


class TestLegacyEra:
    @pytest.mark.asyncio
    async def test_accept_previews_then_writes(self, sn_mock: Mock) -> None:
        init_test_services(write_confirm=True)
        seen: List[str] = []

        async def handler(message, response_type, params, context):
            seen.append(message)
            return True

        async with Client(mcp, mode="legacy", elicitation_handler=handler) as client:
            await client.call_tool("update_record", UPDATE_ARGS)
        assert _methods(sn_mock) == ["GET", "PATCH"]
        assert seen and seen[0].startswith("Update incident/abc123?")
        assert "INC0010001" in seen[0]
        preview_params = sn_mock.calls[0][2]
        assert preview_params["sysparm_fields"] == "sys_id,number,name,state"

    @pytest.mark.asyncio
    async def test_decline_stops_without_hint(self, sn_mock: Mock) -> None:
        init_test_services(write_confirm=True)
        async with Client(mcp, mode="legacy", elicitation_handler=_decline) as client:
            with pytest.raises(ToolError, match="Declined by user") as exc_info:
                await client.call_tool("update_record", UPDATE_ARGS)
        assert "confirm=true" not in str(exc_info.value)
        assert _methods(sn_mock) == ["GET"]

    @pytest.mark.asyncio
    async def test_cancel_falls_back_to_confirm_arg(self, sn_mock: Mock) -> None:
        """Claude Desktop/Cowork answer with a synthetic cancel within ms."""
        init_test_services(write_confirm=True)
        async with Client(mcp, mode="legacy", elicitation_handler=_cancel) as client:
            with pytest.raises(ToolError, match="confirmation_required") as exc_info:
                await client.call_tool("update_record", UPDATE_ARGS)
            payload = json.loads(str(exc_info.value))
            assert payload["table"] == "incident" and "confirm=true" in payload["hint"]
            assert payload["preview"]["number"] == "INC0010001"
            await client.call_tool("update_record", {**UPDATE_ARGS, "confirm": True})
        assert _methods(sn_mock) == ["GET", "GET", "PATCH"]

    @pytest.mark.asyncio
    async def test_no_handler_falls_back_without_leaking_mcperror(
        self, sn_mock: Mock
    ) -> None:
        init_test_services(write_confirm=True)
        async with Client(mcp, mode="legacy") as client:
            with pytest.raises(ToolError, match="confirmation_required"):
                await client.call_tool(
                    "delete_record", {"table_name": "incident", "sys_id": "abc123"}
                )
            await client.call_tool(
                "delete_record",
                {"table_name": "incident", "sys_id": "abc123", "confirm": True},
            )
        assert _methods(sn_mock) == ["GET", "GET", "DELETE"]


class TestModernEra:
    @pytest.mark.asyncio
    async def test_guard_round_trip_then_write(self, sn_mock: Mock) -> None:
        init_test_services(write_confirm=True)
        seen: List[Any] = []

        async def handler(message, response_type, params, context):
            seen.append((message, params.requested_schema))
            return True

        async with Client(mcp, elicitation_handler=handler) as client:
            result = await client.call_tool(
                "update_ci", {"sys_id": "abc123", "data": {"name": "x"}}
            )
        assert result.data["sys_id"] == "abc123"
        # Leg 1: preview GET then ask; leg 2: preview GET again then PATCH.
        assert _methods(sn_mock) == ["GET", "GET", "PATCH"]
        assert seen[0][0].startswith("Update cmdb_ci/abc123?")
        assert seen[0][1]["properties"]["value"]["type"] == "boolean"

    @pytest.mark.asyncio
    async def test_decline_stops(self, sn_mock: Mock) -> None:
        init_test_services(write_confirm=True)
        async with Client(mcp, elicitation_handler=_decline) as client:
            with pytest.raises(ToolError, match="Declined by user"):
                await client.call_tool("update_record", UPDATE_ARGS)
        assert "PATCH" not in _methods(sn_mock)

    @pytest.mark.asyncio
    async def test_cancel_then_confirm_arg(self, sn_mock: Mock) -> None:
        init_test_services(write_confirm=True)
        async with Client(mcp, elicitation_handler=_cancel) as client:
            with pytest.raises(ToolError, match="confirmation_required"):
                await client.call_tool("update_record", UPDATE_ARGS)
            await client.call_tool("update_record", {**UPDATE_ARGS, "confirm": True})
        assert "PATCH" in _methods(sn_mock)

    @pytest.mark.asyncio
    async def test_client_without_capability_never_gets_input_required(
        self, sn_mock: Mock
    ) -> None:
        init_test_services(write_confirm=True)
        async with Client(mcp) as client:
            with pytest.raises(ToolError, match="confirmation_required"):
                await client.call_tool("update_record", UPDATE_ARGS)
            await client.call_tool("update_record", {**UPDATE_ARGS, "confirm": True})
        assert _methods(sn_mock) == ["GET", "GET", "PATCH"]

    @pytest.mark.asyncio
    async def test_tampered_request_state_is_rejected_by_sdk(
        self, sn_mock: Mock
    ) -> None:
        """The SDK seals request_state; a tampered value never reaches the tool."""
        from mcp.shared.exceptions import MCPError

        init_test_services(write_confirm=True)
        async with Client(mcp, elicitation_handler=_accept) as client:
            first = await client.session.call_tool(
                "update_record", UPDATE_ARGS, allow_input_required=True
            )
            assert getattr(first, "result_type", None) == "input_required"
            with pytest.raises((MCPError, ToolError)):
                await client.session.call_tool(
                    "update_record",
                    UPDATE_ARGS,
                    input_responses={
                        "confirm": {"action": "accept", "content": {"value": True}}
                    },
                    request_state="tampered",
                    allow_input_required=True,
                )
        assert "PATCH" not in _methods(sn_mock)


@pytest.mark.asyncio
async def test_audit_records_confirm_legs(sn_mock: Mock, tmp_path) -> None:
    from servicenow_mcp.middleware import audit

    init_test_services(write_confirm=True)
    path = tmp_path / "audit.jsonl"
    audit.configure_audit_log(str(path))
    async with Client(mcp, elicitation_handler=_accept) as client:
        await client.call_tool("update_record", UPDATE_ARGS)
    audit.configure_audit_log("off")
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert [line["outcome"] for line in lines] == ["input_required", "ok"]
    assert lines[0]["confirm"] == "prompted" and lines[1]["round"] == 2
