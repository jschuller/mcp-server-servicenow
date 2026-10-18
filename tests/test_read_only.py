"""--read-only: write tools disappear and non-GET requests are refused."""

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from servicenow_mcp import server
from servicenow_mcp.server import mcp
from servicenow_mcp.utils.http import ServiceNowAPIError
from tests.conftest import init_test_services
from tests.inventory import ALL_TOOLS, READ_TOOLS


@pytest.mark.asyncio
async def test_disable_write_tag_hides_only_tools() -> None:
    init_test_services()
    mcp.disable(tags={"write"}, components={"tool"})
    async with Client(mcp) as client:
        tools = await client.list_tools()
        assert len(tools) == len(READ_TOOLS)
        assert all(
            "write" not in (t.meta or {}).get("_fastmcp", {}).get("tags", [])
            for t in tools
        )
        assert (
            len(await client.list_resources()) == 19
        )  # 4 static + 15 skill:// entries
        assert len(await client.list_resource_templates()) == 1
        with pytest.raises(ToolError, match="Unknown tool"):
            await client.call_tool(
                "create_record", {"table_name": "incident", "data": {"x": 1}}
            )


@pytest.mark.asyncio
async def test_enable_restores_write_tools() -> None:
    init_test_services()
    mcp.disable(tags={"write"}, components={"tool"})
    mcp.enable(tags={"write"}, components={"tool"})
    async with Client(mcp) as client:
        assert len(await client.list_tools()) == len(ALL_TOOLS)


def test_make_sn_request_refuses_non_get_in_read_only(monkeypatch) -> None:
    init_test_services(read_only=True)
    calls = []
    monkeypatch.setattr(
        "servicenow_mcp.utils.http.api_request",
        lambda *a, **k: calls.append((a, k)),
    )
    with pytest.raises(ServiceNowAPIError, match="read-only mode"):
        server.make_sn_request("POST", "https://test.service-now.com/api/now/table/x")
    with pytest.raises(ServiceNowAPIError, match="read-only mode"):
        server.make_sn_request("delete", "https://test.service-now.com/api/now/table/x")
    assert calls == []


def test_make_sn_request_allows_get_in_read_only(monkeypatch) -> None:
    init_test_services(read_only=True)
    seen = {}

    def fake_api_request(method, url, *args, **kwargs):
        seen["method"] = method
        return "response"

    monkeypatch.setattr("servicenow_mcp.utils.http.api_request", fake_api_request)
    assert server.make_sn_request("GET", "https://x/api/now/table/y") == "response"
    assert seen["method"] == "GET"
