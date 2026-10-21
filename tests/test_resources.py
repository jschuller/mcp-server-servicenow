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


def _instance(monkeypatch, props, user=None, props_error=None) -> dict:
    """Read servicenow://instance with sys_properties and the caller mocked."""
    import asyncio
    import json
    from unittest.mock import Mock

    from servicenow_mcp import resources
    from servicenow_mcp.utils.http import ServiceNowAPIError
    from tests.conftest import sn_response

    if props_error:
        mock = Mock(side_effect=ServiceNowAPIError(props_error))
    else:
        mock = Mock(return_value=sn_response({"result": props}))
    monkeypatch.setattr(resources, "make_sn_request", mock)
    caller = {
        "user_name": "svc.reader",
        "user_display_name": "Reader",
        "user_email": "",
        "roles": ["itil"],
        "time_zone": "",
        **(user or {}),
    }
    fetch = Mock(return_value=caller)
    monkeypatch.setattr(resources, "fetch_current_user", fetch)

    async def read() -> dict:
        async with Client(mcp) as client:
            content = await client.read_resource("servicenow://instance")
        return json.loads(content[0].text)

    payload = asyncio.run(read())
    # The caller's own zone is what display values use.
    assert fetch.call_args.args[2] == "time_zone"
    assert mock.call_args.kwargs["params"]["sysparm_query"] == (
        "nameINglide.war,glide.sys.default.tz,glide.product.version,glide.sys.timezone"
    )
    return payload


class TestInstanceResource:
    def test_reads_the_build_and_zones(self, monkeypatch) -> None:
        payload = _instance(
            monkeypatch,
            [
                {
                    "name": "glide.war",
                    "value": "glide-brazil-08-25-2026__patch0-08-26-2026_09-22-2026_1636.zip",
                },
                {"name": "glide.sys.default.tz", "value": "America/New_York"},
            ],
            user={"time_zone": "Europe/Berlin"},
        )
        assert payload["version"] == (
            "glide-brazil-08-25-2026__patch0-08-26-2026_09-22-2026_1636"
        )
        assert payload["release_family"] == "brazil"
        assert payload["timezone"] == "America/New_York"
        assert payload["user"]["time_zone"] == "Europe/Berlin"
        assert "unavailable" not in payload

    def test_falls_back_to_the_older_names(self, monkeypatch) -> None:
        payload = _instance(
            monkeypatch,
            [
                {"name": "glide.product.version", "value": "Tokyo Patch 4"},
                {"name": "glide.sys.timezone", "value": "US/Pacific"},
            ],
            user={"time_zone": "US/Pacific"},
        )
        assert payload["version"] == "Tokyo Patch 4"
        assert "release_family" not in payload
        assert payload["timezone"] == "US/Pacific"

    def test_hidden_properties_are_named_not_dropped(self, monkeypatch) -> None:
        payload = _instance(monkeypatch, [])
        assert "version" not in payload and "timezone" not in payload
        unavailable = payload["unavailable"]
        assert "needs admin" in unavailable["version"]
        assert "needs admin" in unavailable["timezone"]
        assert payload["user"]["time_zone"] is None
        assert "instance default" in unavailable["user.time_zone"]

    def test_an_empty_default_zone(self, monkeypatch) -> None:
        payload = _instance(
            monkeypatch,
            [
                {"name": "glide.war", "value": "glide-australia-x.zip"},
                {"name": "glide.sys.default.tz", "value": ""},
            ],
        )
        assert payload["release_family"] == "australia"
        assert "built-in default" in payload["unavailable"]["timezone"]

    def test_a_failed_read_says_why(self, monkeypatch) -> None:
        payload = _instance(monkeypatch, [], props_error="Access denied (403). More")
        assert payload["unavailable"]["version"] == (
            "sys_properties could not be read: Access denied (403)"
        )

    def test_an_admin_without_the_properties(self, monkeypatch) -> None:
        # Readable sys_properties, but neither property set: not "needs admin".
        payload = _instance(
            monkeypatch,
            [{"name": "glide.sys.timezone", "value": ""}],
            user={"roles": None, "time_zone": None},
        )
        unavailable = payload["unavailable"]
        assert "not set, or not readable" in unavailable["version"]
        assert "empty or not readable" in unavailable["timezone"]
        assert unavailable["user.roles"] == "the caller's role rows could not be read"
        assert unavailable["user.time_zone"] == "sys_user.time_zone is not readable"

    def test_an_unreadable_caller(self, monkeypatch) -> None:
        from unittest.mock import Mock

        from servicenow_mcp import resources

        payload = _instance(monkeypatch, [])
        monkeypatch.setattr(
            resources, "fetch_current_user", Mock(side_effect=RuntimeError("boom. x"))
        )
        import asyncio
        import json

        async def read() -> dict:
            async with Client(mcp) as client:
                content = await client.read_resource("servicenow://instance")
            return json.loads(content[0].text)

        payload = asyncio.run(read())
        assert "user" not in payload
        assert payload["unavailable"]["user"] == "sys_user could not be read: boom"
        monkeypatch.setattr(resources, "fetch_current_user", Mock(return_value={}))
        payload = asyncio.run(read())
        assert payload["unavailable"]["user"] == (
            "the caller's sys_user row could not be read"
        )
