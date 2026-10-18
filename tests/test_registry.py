"""Registry regression tests for tools, resources, and skills.

Safety net: the tools in tests/inventory.py, 19 static resources (4 hand-written + 15 skill:// entries)
and 1 resource template must stay registered exactly.
"""

import pytest
from fastmcp import Client

from servicenow_mcp.server import mcp, init_services
from tests.inventory import ALL_TOOLS, READ_TOOLS, WRITE_TOOLS
from servicenow_mcp.utils.config import (
    AuthConfig,
    AuthType,
    BasicAuthConfig,
    ServerConfig,
)


EXPECTED_TOOLS = ALL_TOOLS

SKILLS = (
    "analyzing-access",
    "exploring-tables",
    "reviewing-update-sets",
    "servicenow-cmdb",
)
EXPECTED_RESOURCES = {
    "servicenow://instance",
    "servicenow://update-set/current",
    "servicenow://cmdb/classes",
    "servicenow://help/query-syntax",
    *(f"skill://{n}/SKILL.md" for n in SKILLS),
    *(f"skill://{n}/_manifest" for n in SKILLS),
    "skill://analyzing-access/references/access-errors.md",
    "skill://analyzing-access/references/acl-evaluation.md",
    "skill://exploring-tables/references/query-syntax.md",
    "skill://exploring-tables/references/history-and-references.md",
    "skill://reviewing-update-sets/references/update-set-fields.md",
    "skill://servicenow-cmdb/references/cmdb-tables.md",
    "skill://servicenow-cmdb/references/csdm5.md",
}
EXPECTED_TEMPLATES = {"servicenow://schema/{table_name}"}


@pytest.fixture(autouse=True)
def _init_services():
    """Ensure services are initialized and tools are registered."""
    config = ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="admin", password="test123"),
        ),
    )
    init_services(config)

    # Import tool modules to trigger registration
    import servicenow_mcp.tools.table_tools  # noqa: F401
    import servicenow_mcp.tools.cmdb_tools  # noqa: F401
    import servicenow_mcp.tools.system_tools  # noqa: F401
    import servicenow_mcp.tools.update_set_tools  # noqa: F401
    import servicenow_mcp.resources  # noqa: F401


class TestToolRegistry:
    @pytest.mark.asyncio
    async def test_exact_tool_count(self) -> None:
        """Exactly the inventory's tools must be registered."""
        async with Client(mcp) as client:
            tools = await client.list_tools()
            assert len(tools) == len(EXPECTED_TOOLS), (
                f"Expected {len(EXPECTED_TOOLS)} tools, got {len(tools)}: "
                f"{sorted(t.name for t in tools)}"
            )

    @pytest.mark.asyncio
    async def test_read_and_write_tags_match_the_inventory(self) -> None:
        """READ_TOOLS carry the read tag and WRITE_TOOLS the write tag."""
        tools = await mcp.list_tools()
        tagged = {t.name: t.tags for t in tools}
        assert {n for n, tags in tagged.items() if "read" in tags} == READ_TOOLS
        assert {n for n, tags in tagged.items() if "write" in tags} == WRITE_TOOLS

    @pytest.mark.asyncio
    async def test_all_expected_tools_present(self) -> None:
        """Every expected tool name must be in the registry."""
        async with Client(mcp) as client:
            tools = await client.list_tools()
            registered = {t.name for t in tools}
            missing = EXPECTED_TOOLS - registered
            assert not missing, f"Missing tools: {missing}"

    @pytest.mark.asyncio
    async def test_no_unexpected_tools(self) -> None:
        """No tools beyond the inventory."""
        async with Client(mcp) as client:
            tools = await client.list_tools()
            registered = {t.name for t in tools}
            extra = registered - EXPECTED_TOOLS
            assert not extra, f"Unexpected tools: {extra}"

    @pytest.mark.asyncio
    async def test_all_tools_have_description(self) -> None:
        """Every tool must have a non-empty description."""
        async with Client(mcp) as client:
            tools = await client.list_tools()
            for tool in tools:
                assert tool.description, f"Tool '{tool.name}' has no description"


class TestResourceRegistry:
    @pytest.mark.asyncio
    async def test_exact_resource_set(self) -> None:
        """Exactly the 19 static resources — no extras, none missing."""
        async with Client(mcp) as client:
            registered = {str(r.uri) for r in await client.list_resources()}
        assert registered == EXPECTED_RESOURCES, (
            f"missing={EXPECTED_RESOURCES - registered} extra={registered - EXPECTED_RESOURCES}"
        )

    @pytest.mark.asyncio
    async def test_exact_template_set(self) -> None:
        async with Client(mcp) as client:
            templates = {
                str(t.uri_template) for t in await client.list_resource_templates()
            }
        assert templates == EXPECTED_TEMPLATES

    @pytest.mark.asyncio
    async def test_all_resources_have_description(self) -> None:
        async with Client(mcp) as client:
            for r in await client.list_resources():
                assert r.description, f"Resource '{r.uri}' has no description"
