"""Integration smoke tests against a live ServiceNow PDI.

Run with: SERVICENOW_INSTANCE_URL=... SERVICENOW_USERNAME=... SERVICENOW_PASSWORD=... python -m pytest tests/integration/ -v
"""

import os

import pytest
from fastmcp import Client

from servicenow_mcp.server import mcp, init_services
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


def _get_env_or_skip(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        pytest.skip(f"{name} not set")
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
