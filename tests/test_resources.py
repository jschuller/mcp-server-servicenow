"""Tests for MCP resource registration via FastMCP."""

import pytest
from fastmcp import Client

from servicenow_mcp.server import mcp, init_services
from servicenow_mcp.utils.config import (
    AuthConfig,
    AuthType,
    BasicAuthConfig,
    ServerConfig,
)


@pytest.fixture(autouse=True)
def _init_services():
    """Ensure services are initialized and resources are registered."""
    config = ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="admin", password="test123"),
        ),
    )
    init_services(config)

    import servicenow_mcp.tools.table_tools  # noqa: F401
    import servicenow_mcp.resources  # noqa: F401


class TestResourceRegistration:
    @pytest.mark.asyncio
    async def test_static_resources_listed(self) -> None:
        """Static resources (no URI params) appear in list_resources."""
        async with Client(mcp) as client:
            resources = await client.list_resources()
            uris = [str(r.uri) for r in resources]
            assert "servicenow://instance" in uris
            assert "servicenow://update-set/current" in uris
            assert "servicenow://cmdb/classes" in uris
            assert "servicenow://help/query-syntax" in uris

    @pytest.mark.asyncio
    async def test_schema_template_listed(self) -> None:
        """Parameterized schema resource appears in list_resource_templates."""
        async with Client(mcp) as client:
            templates = await client.list_resource_templates()
            template_uris = [str(t.uriTemplate) for t in templates]
            assert any("schema" in uri and "table_name" in uri for uri in template_uris)


class TestQuerySyntaxResource:
    @pytest.mark.asyncio
    async def test_returns_markdown_content(self) -> None:
        """query-syntax resource returns markdown without API calls."""
        async with Client(mcp) as client:
            content = await client.read_resource("servicenow://help/query-syntax")
            text = content[0].text if hasattr(content[0], "text") else str(content[0])
            assert "Encoded Query Syntax" in text
            assert "STARTSWITH" in text
            assert "ORDERBY" in text

    @pytest.mark.asyncio
    async def test_includes_common_operators(self) -> None:
        """query-syntax covers the operators LLMs most commonly hallucinate."""
        async with Client(mcp) as client:
            content = await client.read_resource("servicenow://help/query-syntax")
            text = content[0].text if hasattr(content[0], "text") else str(content[0])
            for op in [
                "LIKE",
                "IN",
                "ISEMPTY",
                "ISNOTEMPTY",
                "INSTANCEOF",
                "^OR",
                "^NQ",
            ]:
                assert op in text, f"Missing operator: {op}"
