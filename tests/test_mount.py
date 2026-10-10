"""AD-2: the server mounted into another FastMCP server keeps its governance.

A consumer composes with ``parent.mount(mcp, namespace="snow")``. Policy and
audit must still apply to calls routed through the parent, and the URIs that
``render_instructions("snow")`` names must be the ones the parent serves.
"""

import json
import re

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from servicenow_mcp.middleware.audit import configure_audit_log
from servicenow_mcp.server import mcp, render_instructions
from tests.conftest import init_test_services


@pytest.fixture
def parent() -> FastMCP:
    orchestrator = FastMCP("orchestrator")
    orchestrator.mount(mcp, namespace="snow")
    return orchestrator


async def test_policy_and_audit_survive_mount(parent: FastMCP, tmp_path) -> None:
    init_test_services(table_denylist=["incident"])
    log = tmp_path / "audit.jsonl"
    configure_audit_log(str(log))

    async with Client(parent) as client:
        with pytest.raises(ToolError, match="blocked by SERVICENOW_TABLE_DENYLIST"):
            await client.call_tool("snow_list_records", {"table_name": "incident"})

    records = [json.loads(line) for line in log.read_text().splitlines()]
    assert any(
        r["event"] == "tool_call"
        and r["name"] == "list_records"
        and r["outcome"] == "denied"
        for r in records
    )


async def test_rendered_uris_are_the_mounted_ones(parent: FastMCP) -> None:
    init_test_services()
    async with Client(parent) as client:
        served = {str(r.uri) for r in await client.list_resources()}
        # FastMCP does not forward a mounted server's instructions.
        assert not client.instructions

    named = set(re.findall(r"(?:skill|servicenow)://\S+", render_instructions("snow")))
    assert named == {
        "skill://snow/triaging-incidents/SKILL.md",
        "skill://snow/servicenow-cmdb/SKILL.md",
        "skill://snow/reviewing-update-sets/SKILL.md",
        "skill://snow/exploring-tables/SKILL.md",
        "servicenow://snow/help/query-syntax",
    }
    assert named <= served


def test_default_render_is_the_wire_text() -> None:
    from servicenow_mcp.server import SERVER_INSTRUCTIONS

    assert render_instructions() == SERVER_INSTRUCTIONS
    assert "skill://triaging-incidents/SKILL.md" in SERVER_INSTRUCTIONS
