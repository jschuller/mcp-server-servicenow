"""Every tool carries MCP annotations consistent with its read/write tag."""

import pytest
from fastmcp import Client

from servicenow_mcp.server import mcp
from tests.conftest import init_test_services

DESTRUCTIVE = {"update_record", "update_ci", "delete_record"}
CREATES = {"create_record", "create_ci", "create_update_set", "set_current_update_set"}


@pytest.fixture(autouse=True)
def _services():
    init_test_services()


@pytest.mark.asyncio
async def test_every_tool_has_annotations() -> None:
    tools = await mcp.list_tools()
    assert len(tools) == 19
    for tool in tools:
        assert tool.annotations is not None, f"{tool.name} lacks annotations"


@pytest.mark.asyncio
async def test_read_tools_are_read_only_hints() -> None:
    for tool in await mcp.list_tools():
        assert tool.annotations is not None
        if "read" in tool.tags:
            assert tool.annotations.read_only_hint is True, tool.name
            assert tool.annotations.destructive_hint is False, tool.name
        else:
            assert "write" in tool.tags, tool.name
            assert tool.annotations.read_only_hint is False, tool.name


@pytest.mark.asyncio
async def test_destructive_hint_matches_tool_semantics() -> None:
    tools = {t.name: t for t in await mcp.list_tools()}
    for name in DESTRUCTIVE:
        assert tools[name].annotations.destructive_hint is True, name
    for name in CREATES:
        assert tools[name].annotations.destructive_hint is False, name


@pytest.mark.asyncio
async def test_annotations_reach_the_wire_in_camel_case() -> None:
    async with Client(mcp) as client:
        tools = {t.name: t for t in await client.list_tools()}
    wire = tools["delete_record"].model_dump(by_alias=True)["annotations"]
    assert wire["readOnlyHint"] is False
    assert wire["destructiveHint"] is True
    wire = tools["list_records"].model_dump(by_alias=True)["annotations"]
    assert wire["readOnlyHint"] is True
