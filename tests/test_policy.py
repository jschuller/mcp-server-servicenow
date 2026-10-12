"""PolicyMiddleware: identifier validation and query hardening."""

from unittest.mock import Mock

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from servicenow_mcp.middleware.policy import find_unsafe_js
from servicenow_mcp import server
from servicenow_mcp.server import mcp
from servicenow_mcp.tools import cmdb_tools, system_tools, table_tools
from servicenow_mcp.utils.http import build_url
from tests.conftest import init_test_services, sn_response

# Every javascript: helper the shipped skills and the query-syntax resource teach.
TAUGHT_HELPERS = [
    "sys_created_on>=javascript:gs.daysAgo(7)",
    "active=true^sys_created_on>=javascript:gs.daysAgoStart(1)",
    "active=true^sla_due<javascript:gs.daysAgoEnd(0)",
    "sys_created_on>=javascript:gs.monthsAgoStart(1)",
    "sys_updated_on>=javascript:gs.beginningOfToday()",
    "sys_updated_on>=javascript:gs.beginningOfLastWeek()",
    "sys_created_on>=javascript:gs.beginningOfLastMonth()",
    "state=6^ORstate=7^resolved_at>=javascript:gs.daysAgoStart(7)^active=true",
    "sys_created_on<javascript:gs.nowDateTime()",
    # Ranges as the list UI writes them: ends separated by "@".
    "opened_atONToday@javascript:gs.beginningOfToday()@javascript:gs.endOfToday()",
    "opened_atON2026-10-01@javascript:gs.dateGenerate('2026-10-01','start')"
    "@javascript:gs.dateGenerate('2026-10-01','end')",
    "opened_atBETWEENjavascript:gs.dateGenerate('2026-10-01','00:00:00')"
    "@javascript:gs.dateGenerate('2026-10-07','23:59:59')^active=true",
    "opened_atBETWEENjavascript:gs.daysAgoStart(7)@javascript:gs.daysAgoEnd(0)",
]

UNSAFE = [
    "user_name=javascript:gs.getUserName()",
    "sys_created_on>=javascript:gs.daysAgo(7)^ORuser_name=javascript:gs.getUserName()",
    "x=javascript:gs.daysAgo(7);gs.setProperty('a','b')",
    "x=JavaScript:new GlideRecord('sys_user')",
    "x=javascript:gs.daysAgo(gs.getProperty('x'))",
    "x=javascript:gs.daysAgo(7) ^y=1",
    # A safe first end does not excuse an unsafe second one.
    "opened_atONToday@javascript:gs.beginningOfToday()@javascript:gs.getUserID()",
    "opened_atBETWEENjavascript:gs.daysAgoStart(7)@javascript:gs.daysAgoEnd(0);gs.log(1)",
    # dateGenerate takes literals only.
    "opened_atON2026-10-01@javascript:gs.dateGenerate(gs.getUserID(),'start')",
    "opened_atON2026-10-01@javascript:gs.dateGenerate('2026-10-01',gs.getUserID())",
    "opened_atON2026-10-01@javascript:gs.dateGenerate('2026-10-01','start')+1",
    "opened_atON2026-10-01@javascript:gs.dateGenerate('2026-10-01','middle')",
]


@pytest.mark.parametrize("query", TAUGHT_HELPERS)
def test_taught_date_helpers_are_safe(query: str) -> None:
    assert find_unsafe_js(query) is None


@pytest.mark.parametrize("query", UNSAFE)
def test_unsafe_script_is_detected(query: str) -> None:
    assert find_unsafe_js(query) is not None


def test_build_url_encodes_segments() -> None:
    url = build_url("https://x/api/now", "table", "incident", "../sys_user/abc")
    assert url == "https://x/api/now/table/incident/..%2Fsys_user%2Fabc"
    assert build_url("https://x/api/now", "table", "a?b=c") == (
        "https://x/api/now/table/a%3Fb%3Dc"
    )


@pytest.fixture
def table_mock(monkeypatch) -> Mock:
    mock = Mock(return_value=sn_response({"result": [{"sys_id": "1"}]}))
    monkeypatch.setattr(table_tools, "make_sn_request", mock)
    monkeypatch.setattr(cmdb_tools, "make_sn_request", mock)
    monkeypatch.setattr(system_tools, "make_sn_request", mock)
    return mock


async def _call(name: str, args: dict) -> None:
    async with Client(mcp) as client:
        await client.call_tool(name, args)


class TestTableNames:
    @pytest.mark.asyncio
    async def test_class_name_is_validated(self, table_mock: Mock) -> None:
        init_test_services()
        with pytest.raises(ToolError, match="Invalid table name"):
            await _call("list_ci", {"class_name": "cmdb_ci^ORx"})
        table_mock.assert_not_called()
        await _call("list_ci", {"class_name": "cmdb_ci_server"})
        table_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_schema_resource_is_validated(self, monkeypatch) -> None:
        init_test_services()
        monkeypatch.setattr(
            "servicenow_mcp.server.make_sn_request",
            Mock(return_value=sn_response({"result": []})),
        )
        async with Client(mcp) as client:
            with pytest.raises(Exception, match="Invalid table name"):
                await client.read_resource("servicenow://schema/incident%5EORx")


class TestIdentifiers:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "table", ["incident/../sys_user", "incident^ORjavascript:1", "a b", ""]
    )
    async def test_invalid_table_name(self, table_mock: Mock, table: str) -> None:
        init_test_services()
        with pytest.raises(ToolError, match="Invalid table name"):
            await _call("list_records", {"table_name": table})
        table_mock.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "sys_id", ["../sys_user/abc", "abc?sysparm_query=x", "a^ORb"]
    )
    async def test_invalid_sys_id(self, table_mock: Mock, sys_id: str) -> None:
        init_test_services()
        with pytest.raises(ToolError, match="Invalid sys_id"):
            await _call("get_record", {"table_name": "incident", "sys_id": sys_id})
        with pytest.raises(ToolError, match="Invalid sys_id"):
            await _call("get_ci_relationships", {"sys_id": sys_id})
        table_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_invalid_order_by_and_fields(self, table_mock: Mock) -> None:
        init_test_services()
        with pytest.raises(ToolError, match="Invalid order_by"):
            await _call(
                "list_records",
                {"table_name": "incident", "order_by": "number^ORDERBYx"},
            )
        with pytest.raises(ToolError, match="Invalid fields"):
            await _call("list_records", {"table_name": "incident", "fields": "a;b"})
        await _call(
            "list_records",
            {
                "table_name": "incident",
                "order_by": "-sys_updated_on",
                "fields": "number, caller_id.name",
            },
        )

    @pytest.mark.asyncio
    async def test_invalid_state_and_update_set_id(self, monkeypatch) -> None:
        from servicenow_mcp.tools import update_set_tools

        mock = Mock(return_value=sn_response({"result": []}))
        monkeypatch.setattr(update_set_tools, "make_sn_request", mock)
        init_test_services()
        with pytest.raises(ToolError, match="Invalid state"):
            await _call("list_update_sets", {"state": "in progress^ORx=1"})
        with pytest.raises(ToolError, match="Invalid update_set_sys_id"):
            await _call("list_update_set_changes", {"update_set_sys_id": "a^ORb"})
        await _call("list_update_sets", {"state": "in progress"})
        mock.assert_called_once()


class TestQueryPolicy:
    @pytest.mark.asyncio
    async def test_unsafe_js_rejected_in_query_and_having(
        self, table_mock: Mock
    ) -> None:
        init_test_services()
        with pytest.raises(ToolError, match="unsafe javascript"):
            await _call(
                "list_records",
                {"table_name": "incident", "query": "x=javascript:gs.getUserName()"},
            )
        with pytest.raises(ToolError, match="unsafe javascript"):
            await _call(
                "aggregate_records",
                {"table_name": "incident", "having": "COUNT>javascript:gs.getUserID()"},
            )
        table_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_taught_helpers_pass_through_tool(self, table_mock: Mock) -> None:
        init_test_services()
        for query in TAUGHT_HELPERS:
            await _call("list_records", {"table_name": "incident", "query": query})
        assert table_mock.call_count == len(TAUGHT_HELPERS)

    @pytest.mark.asyncio
    async def test_allow_js_queries_bypasses(self, table_mock: Mock) -> None:
        init_test_services(allow_js_queries=True)
        await _call(
            "list_records",
            {"table_name": "incident", "query": "x=javascript:gs.getUserName()"},
        )
        table_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_server_authored_js_is_unaffected(self, monkeypatch) -> None:
        """get_current_user's internal gs.getUserName() query never hits the policy."""
        init_test_services()

        def fake(method, url, timeout, params=None, json_data=None):
            if url.endswith("/sys_user_has_role"):
                assert params["sysparm_query"].startswith(
                    "user=javascript:gs.getUserID()"
                )
                return sn_response({"result": [{"role.name": "itil"}]})
            assert params["sysparm_query"] == "user_name=javascript:gs.getUserName()"
            return sn_response({"result": [{"user_name": "admin", "name": "Admin"}]})

        # fetch_current_user resolves make_sn_request from the server module.
        monkeypatch.setattr(server, "make_sn_request", fake)
        async with Client(mcp) as client:
            result = await client.call_tool("get_current_user", {})
        assert result.data["user_name"] == "admin"
        assert result.data["roles"] == ["itil"]
