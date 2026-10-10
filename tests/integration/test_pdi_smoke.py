"""Integration smoke tests against a live ServiceNow instance.

Credentials come only from the environment, as the server itself reads them;
launch under a secret-store wrapper rather than keeping values in a file:

    with-secrets SERVICENOW_API_KEY=svc/homelab/servicenow-<instance>-apikey -- \\
      env SERVICENOW_INSTANCE_URL=https://<instance>.service-now.com \\
          SERVICENOW_API_KEY_HEADER=x-sn-apikey \\
      uv run pytest tests/integration/ -v

With SERVICENOW_API_KEY set the tests use API-key auth; otherwise basic auth
with SERVICENOW_USERNAME / SERVICENOW_PASSWORD. Skipped when nothing is set.
Read-only: nothing on the instance is changed.
"""

import os

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from servicenow_mcp.server import mcp, init_services
from servicenow_mcp.utils.config import (
    ApiKeyConfig,
    AuthConfig,
    AuthType,
    BasicAuthConfig,
    ServerConfig,
)


def _get_env_or_skip(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        pytest.skip(f"{name} not set (see the module docstring)")
    return val


@pytest.fixture(autouse=True, scope="module")
def _init_pdi():
    """Initialize services with live credentials from the environment."""
    instance_url = _get_env_or_skip("SERVICENOW_INSTANCE_URL")
    api_key = os.environ.get("SERVICENOW_API_KEY")
    if api_key:
        auth = AuthConfig(
            type=AuthType.API_KEY,
            api_key=ApiKeyConfig(
                api_key=api_key,
                header_name=os.environ.get(
                    "SERVICENOW_API_KEY_HEADER", "X-ServiceNow-API-Key"
                ),
            ),
        )
    else:
        auth = AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(
                username=_get_env_or_skip("SERVICENOW_USERNAME"),
                password=_get_env_or_skip("SERVICENOW_PASSWORD"),
            ),
        )
    config = ServerConfig(instance_url=instance_url, auth=auth)
    init_services(config)

    import servicenow_mcp.tools.table_tools  # noqa: F401
    import servicenow_mcp.tools.cmdb_tools  # noqa: F401
    import servicenow_mcp.tools.system_tools  # noqa: F401
    import servicenow_mcp.tools.update_set_tools  # noqa: F401
    import servicenow_mcp.resources  # noqa: F401


async def _call(client: Client, tool: str, args: dict, needs: str):
    """call_tool, skipping (not failing) when the identity is refused.

    Least-privilege identities are refused some tools by design: schemas need
    personalize_dictionary, update sets need admin, and an API key needs a REST
    API access policy for each API it calls. A skip names what is missing.
    """
    try:
        return await client.call_tool(tool, args)
    except ToolError as exc:
        if "(401)" in str(exc) or "(403)" in str(exc):
            pytest.skip(f"{tool}: refused for this identity (needs {needs})")
        raise


class TestTableTools:
    @pytest.mark.asyncio
    async def test_list_incidents(self) -> None:
        async with Client(mcp) as client:
            result = await client.call_tool(
                "list_records",
                {
                    "table_name": "incident",
                    "limit": 5,
                },
            )
            assert result is not None

    @pytest.mark.asyncio
    async def test_get_table_schema(self) -> None:
        async with Client(mcp) as client:
            result = await _call(
                client,
                "get_table_schema",
                {"table_name": "incident"},
                "personalize_dictionary",
            )
            assert result is not None
            data = result.data
            # Inherited fields: incident's `number` lives on task (v0.7.0)
            assert data["hierarchy"][:2] == ["incident", "task"]
            by_name = {f["name"]: f for f in data["fields"]}
            assert by_name["number"]["defined_in"] == "task"
            assert by_name["number"]["mandatory"] in ("true", "false")

    @pytest.mark.asyncio
    async def test_audit_line_written(self, tmp_path) -> None:
        import json

        from servicenow_mcp.middleware.audit import configure_audit_log

        path = tmp_path / "audit.jsonl"
        configure_audit_log(str(path))
        try:
            async with Client(mcp) as client:
                await client.call_tool(
                    "list_records", {"table_name": "incident", "limit": 1}
                )
        finally:
            configure_audit_log("off")
        line = json.loads(path.read_text().splitlines()[0])
        assert line["name"] == "list_records" and line["outcome"] == "ok"
        assert line["auth_mode"] == "service-account" and line["user"]


class TestSystemTools:
    @pytest.mark.asyncio
    async def test_get_current_user(self) -> None:
        async with Client(mcp) as client:
            result = await client.call_tool("get_current_user", {})
            assert result is not None

    @pytest.mark.asyncio
    async def test_get_system_properties(self) -> None:
        async with Client(mcp) as client:
            result = await client.call_tool(
                "get_system_properties",
                {
                    "limit": 5,
                },
            )
            assert result is not None


class TestCMDBTools:
    @pytest.mark.asyncio
    async def test_list_ci(self) -> None:
        async with Client(mcp) as client:
            result = await client.call_tool(
                "list_ci",
                {
                    "class_name": "cmdb_ci_computer",
                    "limit": 3,
                },
            )
            assert result is not None


class TestUpdateSetTools:
    @pytest.mark.asyncio
    async def test_list_update_sets(self) -> None:
        async with Client(mcp) as client:
            result = await _call(
                client, "list_update_sets", {"limit": 5}, "admin on sys_update_set"
            )
            assert result is not None


class TestAggregateRecords:
    @pytest.mark.asyncio
    async def test_count_without_group_by(self) -> None:
        """Stats API returns a dict without group_by."""
        async with Client(mcp) as client:
            result = await _call(
                client,
                "aggregate_records",
                {"table_name": "incident", "count": True},
                "an Aggregate API access policy for API keys",
            )
            assert result is not None

    @pytest.mark.asyncio
    async def test_count_with_group_by(self) -> None:
        """Stats API returns a list with group_by — must be wrapped in a dict."""
        async with Client(mcp) as client:
            result = await _call(
                client,
                "aggregate_records",
                {"table_name": "incident", "count": True, "group_by": "priority"},
                "an Aggregate API access policy for API keys",
            )
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
            try:
                content = await client.read_resource("servicenow://schema/incident")
            except Exception as exc:
                if "personalize_dictionary" in str(exc) or "(403)" in str(exc):
                    pytest.skip("schema resource: needs personalize_dictionary")
                raise
            text = content[0].text if hasattr(content[0], "text") else str(content[0])
            assert "incident" in text

    @pytest.mark.asyncio
    async def test_read_cmdb_classes(self) -> None:
        async with Client(mcp) as client:
            content = await client.read_resource("servicenow://cmdb/classes")
            text = content[0].text if hasattr(content[0], "text") else str(content[0])
            assert "classes" in text
            import json

            classes = json.loads(text)["classes"]
            assert classes and all(isinstance(c["super_class"], str) for c in classes)
            assert any(c["super_class"] == "cmdb_ci" for c in classes)

    @pytest.mark.asyncio
    async def test_read_current_update_set(self) -> None:
        async with Client(mcp) as client:
            content = await client.read_resource("servicenow://update-set/current")
            text = content[0].text if hasattr(content[0], "text") else str(content[0])
            # Either returns update set info or error about no current set
            assert "name" in text or "error" in text
