"""Tests for tool schema validation via FastMCP."""

import pytest
from fastmcp import Client

from servicenow_mcp.server import mcp, init_services
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


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

    import servicenow_mcp.tools.table_tools  # noqa: F401
    import servicenow_mcp.tools.cmdb_tools  # noqa: F401
    import servicenow_mcp.tools.system_tools  # noqa: F401
    import servicenow_mcp.tools.update_set_tools  # noqa: F401


def _get_tool_schema(tools, name: str) -> dict:
    """Helper to extract a tool's input schema by name."""
    for t in tools:
        if t.name == name:
            return t.inputSchema
    raise KeyError(f"Tool '{name}' not found")


class TestListRecordsSchema:
    @pytest.mark.asyncio
    async def test_required_fields(self) -> None:
        async with Client(mcp) as client:
            tools = await client.list_tools()
            schema = _get_tool_schema(tools, "list_records")
            assert "table_name" in schema.get("required", [])

    @pytest.mark.asyncio
    async def test_limit_constraints(self) -> None:
        async with Client(mcp) as client:
            tools = await client.list_tools()
            schema = _get_tool_schema(tools, "list_records")
            limit_prop = schema["properties"]["limit"]
            assert limit_prop.get("minimum") == 1 or limit_prop.get("exclusiveMinimum") == 0
            assert limit_prop.get("maximum") == 1000 or limit_prop.get("exclusiveMaximum") == 1001

    @pytest.mark.asyncio
    async def test_default_values(self) -> None:
        async with Client(mcp) as client:
            tools = await client.list_tools()
            schema = _get_tool_schema(tools, "list_records")
            assert schema["properties"]["limit"].get("default") == 20
            assert schema["properties"]["offset"].get("default") == 0


class TestGetRecordSchema:
    @pytest.mark.asyncio
    async def test_required_fields(self) -> None:
        async with Client(mcp) as client:
            tools = await client.list_tools()
            schema = _get_tool_schema(tools, "get_record")
            required = schema.get("required", [])
            assert "table_name" in required
            assert "sys_id" in required


class TestCreateRecordSchema:
    @pytest.mark.asyncio
    async def test_required_fields(self) -> None:
        async with Client(mcp) as client:
            tools = await client.list_tools()
            schema = _get_tool_schema(tools, "create_record")
            required = schema.get("required", [])
            assert "table_name" in required
            assert "data" in required


class TestDeleteRecordSchema:
    @pytest.mark.asyncio
    async def test_required_fields(self) -> None:
        async with Client(mcp) as client:
            tools = await client.list_tools()
            schema = _get_tool_schema(tools, "delete_record")
            required = schema.get("required", [])
            assert "table_name" in required
            assert "sys_id" in required


class TestListCISchema:
    @pytest.mark.asyncio
    async def test_all_optional(self) -> None:
        """list_ci has no required fields (all have defaults)."""
        async with Client(mcp) as client:
            tools = await client.list_tools()
            schema = _get_tool_schema(tools, "list_ci")
            # All params are optional, so required should be empty or absent
            assert not schema.get("required", [])

    @pytest.mark.asyncio
    async def test_default_class_name(self) -> None:
        async with Client(mcp) as client:
            tools = await client.list_tools()
            schema = _get_tool_schema(tools, "list_ci")
            assert schema["properties"]["class_name"].get("default") == "cmdb_ci"


class TestGetCISchema:
    @pytest.mark.asyncio
    async def test_required_sys_id(self) -> None:
        async with Client(mcp) as client:
            tools = await client.list_tools()
            schema = _get_tool_schema(tools, "get_ci")
            assert "sys_id" in schema.get("required", [])


class TestGetTableSchemaSchema:
    @pytest.mark.asyncio
    async def test_required_table_name(self) -> None:
        async with Client(mcp) as client:
            tools = await client.list_tools()
            schema = _get_tool_schema(tools, "get_table_schema")
            assert "table_name" in schema.get("required", [])

    @pytest.mark.asyncio
    async def test_limit_default(self) -> None:
        async with Client(mcp) as client:
            tools = await client.list_tools()
            schema = _get_tool_schema(tools, "get_table_schema")
            assert schema["properties"]["limit"].get("default") == 50


class TestCreateUpdateSetSchema:
    @pytest.mark.asyncio
    async def test_required_name(self) -> None:
        async with Client(mcp) as client:
            tools = await client.list_tools()
            schema = _get_tool_schema(tools, "create_update_set")
            assert "name" in schema.get("required", [])


class TestListUpdateSetChangesSchema:
    @pytest.mark.asyncio
    async def test_required_update_set_sys_id(self) -> None:
        async with Client(mcp) as client:
            tools = await client.list_tools()
            schema = _get_tool_schema(tools, "list_update_set_changes")
            assert "update_set_sys_id" in schema.get("required", [])

    @pytest.mark.asyncio
    async def test_limit_default(self) -> None:
        async with Client(mcp) as client:
            tools = await client.list_tools()
            schema = _get_tool_schema(tools, "list_update_set_changes")
            assert schema["properties"]["limit"].get("default") == 50


class TestAggregateRecordsSchema:
    @pytest.mark.asyncio
    async def test_required_fields(self) -> None:
        async with Client(mcp) as client:
            tools = await client.list_tools()
            schema = _get_tool_schema(tools, "aggregate_records")
            assert "table_name" in schema.get("required", [])

    @pytest.mark.asyncio
    async def test_count_default(self) -> None:
        async with Client(mcp) as client:
            tools = await client.list_tools()
            schema = _get_tool_schema(tools, "aggregate_records")
            assert schema["properties"]["count"].get("default") is True

    @pytest.mark.asyncio
    async def test_aggregate_fields_optional(self) -> None:
        async with Client(mcp) as client:
            tools = await client.list_tools()
            schema = _get_tool_schema(tools, "aggregate_records")
            required = schema.get("required", [])
            for field in ["avg_fields", "min_fields", "max_fields", "sum_fields", "group_by", "query", "having"]:
                assert field not in required, f"{field} should be optional"

    @pytest.mark.asyncio
    async def test_tool_count(self) -> None:
        """Verify total tool count is 19 (18 original + aggregate_records)."""
        async with Client(mcp) as client:
            tools = await client.list_tools()
            assert len(tools) == 19
