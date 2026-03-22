"""Integration smoke tests against a live ServiceNow PDI.

Credentials are loaded from .env.test (gitignored) or environment variables.
Run with: python -m pytest tests/integration/ -v

Create .env.test with:
    SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com
    SERVICENOW_USERNAME=admin
    SERVICENOW_PASSWORD=your-password
"""

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv
from fastmcp import Client

from servicenow_mcp.server import mcp, init_services
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig

# Load .env.test from project root if it exists
_env_test = Path(__file__).resolve().parents[2] / ".env.test"
if _env_test.exists():
    load_dotenv(_env_test)


def _get_env_or_skip(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        pytest.skip(f"{name} not set (create .env.test or set env var)")
    return val


@pytest.fixture(autouse=True, scope="module")
def _init_pdi():
    """Initialize services with real PDI credentials."""
    instance_url = _get_env_or_skip("SERVICENOW_INSTANCE_URL")
    username = _get_env_or_skip("SERVICENOW_USERNAME")
    password = _get_env_or_skip("SERVICENOW_PASSWORD")

    config = ServerConfig(
        instance_url=instance_url,
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username=username, password=password),
        ),
    )
    init_services(config)

    import servicenow_mcp.tools.table_tools  # noqa: F401
    import servicenow_mcp.tools.cmdb_tools  # noqa: F401
    import servicenow_mcp.tools.system_tools  # noqa: F401
    import servicenow_mcp.tools.update_set_tools  # noqa: F401
    import servicenow_mcp.resources  # noqa: F401


class TestTableTools:
    @pytest.mark.asyncio
    async def test_list_incidents(self) -> None:
        async with Client(mcp) as client:
            result = await client.call_tool("list_records", {
                "table_name": "incident",
                "limit": 5,
            })
            assert result is not None

    @pytest.mark.asyncio
    async def test_get_table_schema(self) -> None:
        async with Client(mcp) as client:
            result = await client.call_tool("get_table_schema", {
                "table_name": "incident",
            })
            assert result is not None


class TestSystemTools:
    @pytest.mark.asyncio
    async def test_get_current_user(self) -> None:
        async with Client(mcp) as client:
            result = await client.call_tool("get_current_user", {})
            assert result is not None

    @pytest.mark.asyncio
    async def test_get_system_properties(self) -> None:
        async with Client(mcp) as client:
            result = await client.call_tool("get_system_properties", {
                "limit": 5,
            })
            assert result is not None


class TestCMDBTools:
    @pytest.mark.asyncio
    async def test_list_ci(self) -> None:
        async with Client(mcp) as client:
            result = await client.call_tool("list_ci", {
                "class_name": "cmdb_ci_computer",
                "limit": 3,
            })
            assert result is not None


class TestUpdateSetTools:
    @pytest.mark.asyncio
    async def test_list_update_sets(self) -> None:
        async with Client(mcp) as client:
            result = await client.call_tool("list_update_sets", {
                "limit": 5,
            })
            assert result is not None


class TestAggregateRecords:
    @pytest.mark.asyncio
    async def test_count_without_group_by(self) -> None:
        """Stats API returns a dict without group_by."""
        async with Client(mcp) as client:
            result = await client.call_tool("aggregate_records", {
                "table_name": "incident",
                "count": True,
            })
            assert result is not None

    @pytest.mark.asyncio
    async def test_count_with_group_by(self) -> None:
        """Stats API returns a list with group_by — must be wrapped in a dict."""
        async with Client(mcp) as client:
            result = await client.call_tool("aggregate_records", {
                "table_name": "incident",
                "count": True,
                "group_by": "priority",
            })
            assert result is not None


class TestResources:
    @pytest.mark.asyncio
    async def test_read_query_syntax(self) -> None:
        """Static resource — no API call needed."""
        async with Client(mcp) as client:
            content = await client.read_resource("servicenow://help/query-syntax")
            text = content[0].text if hasattr(content[0], "text") else str(content[0])
            assert "STARTSWITH" in text

    @pytest.mark.asyncio
    async def test_read_instance_info(self) -> None:
        async with Client(mcp) as client:
            content = await client.read_resource("servicenow://instance")
            text = content[0].text if hasattr(content[0], "text") else str(content[0])
            assert "instance_url" in text

    @pytest.mark.asyncio
    async def test_read_schema_template(self) -> None:
        async with Client(mcp) as client:
            content = await client.read_resource("servicenow://schema/incident")
            text = content[0].text if hasattr(content[0], "text") else str(content[0])
            assert "incident" in text

    @pytest.mark.asyncio
    async def test_read_cmdb_classes(self) -> None:
        async with Client(mcp) as client:
            content = await client.read_resource("servicenow://cmdb/classes")
            text = content[0].text if hasattr(content[0], "text") else str(content[0])
            assert "classes" in text

    @pytest.mark.asyncio
    async def test_read_current_update_set(self) -> None:
        async with Client(mcp) as client:
            content = await client.read_resource("servicenow://update-set/current")
            text = content[0].text if hasattr(content[0], "text") else str(content[0])
            # Either returns update set info or error about no current set
            assert "name" in text or "error" in text
