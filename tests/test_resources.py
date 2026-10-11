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
            template_uris = [str(t.uri_template) for t in templates]
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


class TestCmdbClassesResource:
    @pytest.mark.asyncio
    async def test_requests_super_class_name_dot_walk(self, monkeypatch) -> None:
        import json
        from unittest.mock import Mock

        from servicenow_mcp import resources
        from tests.conftest import sn_response

        mock = Mock(
            return_value=sn_response(
                {
                    "result": [
                        {
                            "name": "cmdb_ci_server",
                            "label": "Server",
                            "super_class.name": "cmdb_ci_computer",
                            "super_class": {"link": "l", "value": "ID"},
                        },
                        {"name": "cmdb_ci", "label": "CI", "super_class": ""},
                    ]
                }
            )
        )
        monkeypatch.setattr(resources, "make_sn_request", mock)
        async with Client(mcp) as client:
            content = await client.read_resource("servicenow://cmdb/classes")
        payload = json.loads(content[0].text)
        assert payload["classes"][0]["super_class"] == "cmdb_ci_computer"
        assert payload["classes"][1]["super_class"] == ""
        assert "super_class.name" in mock.call_args.kwargs["params"]["sysparm_fields"]


def _class_rows(start: int, count: int) -> list[dict]:
    return [
        {"name": f"cmdb_ci_{i:04d}", "label": f"C{i}", "super_class": ""}
        for i in range(start, start + count)
    ]


@pytest.mark.asyncio
async def test_cmdb_classes_pages_past_the_first_batch(monkeypatch) -> None:
    """A base instance has 500+ classes; the old single 200-row read cut them off."""
    import json
    from unittest.mock import Mock

    from servicenow_mcp import resources
    from tests.conftest import sn_response

    size = resources.CLASS_PAGE_SIZE
    mock = Mock(
        side_effect=[
            sn_response({"result": _class_rows(0, size)}),
            sn_response({"result": _class_rows(size, 20)}),
        ]
    )
    monkeypatch.setattr(resources, "make_sn_request", mock)
    async with Client(mcp) as client:
        content = await client.read_resource("servicenow://cmdb/classes")
    payload = json.loads(content[0].text)
    assert payload["count"] == size + 20
    assert "truncated" not in payload
    offsets = [c.kwargs["params"]["sysparm_offset"] for c in mock.call_args_list]
    assert offsets == [0, size]


@pytest.mark.asyncio
async def test_cmdb_classes_says_when_it_stops_at_the_bound(monkeypatch) -> None:
    import json
    from unittest.mock import Mock

    from servicenow_mcp import resources
    from tests.conftest import sn_response

    monkeypatch.setattr(resources, "CLASS_PAGE_SIZE", 2)
    monkeypatch.setattr(resources, "MAX_CLASS_PAGES", 3)
    mock = Mock(side_effect=lambda *a, **k: sn_response({"result": _class_rows(0, 2)}))
    monkeypatch.setattr(resources, "make_sn_request", mock)
    async with Client(mcp) as client:
        content = await client.read_resource("servicenow://cmdb/classes")
    payload = json.loads(content[0].text)
    assert payload["count"] == 6 and payload["truncated"] is True
    assert mock.call_count == 3
