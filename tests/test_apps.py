"""--apps: the MCP Apps spike (review_update_set and its ui:// view).

Off by default: nothing is registered, so the tool inventory and the contract
snapshot stay as they are. The in-process tests register the app on a fresh
FastMCP, never on the module-level singleton, so no other test sees the extra
tool; the end-to-end checks of both modes start a fresh interpreter, like the
skills switch tests.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from importlib.resources import files
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from servicenow_mcp import apps, cli
from servicenow_mcp.server import init_services
from tests.conftest import make_server_config, sn_response

UI_MIME = "text/html;profile=mcp-app"
SET_ID = "a" * 32
HEADER = {
    "sys_id": SET_ID,
    "name": "Release 12 fixes",
    "state": "complete",
    "description": "Fixes for release 12",
    "application.name": "Global",
    "sys_created_by": "dev.one",
    "sys_created_on": "2026-11-01 09:00:00",
    "sys_updated_on": "2026-11-10 17:30:00",
}
CHANGES = [
    {
        "sys_id": "b" * 32,
        "name": "sys_script_" + "c" * 32,
        "type": "Business Rule",
        "target_name": "Set assignment group",
        "action": "INSERT_OR_UPDATE",
        "sys_created_by": "dev.one",
        "sys_updated_on": "2026-11-10 17:30:00",
    },
    {
        "sys_id": "d" * 32,
        "name": "sys_script_client_" + "e" * 32,
        "type": "Client Script",
        "target_name": "<img src=x onerror=alert(1)>",
        "action": "DELETE",
        "sys_created_by": "dev.two",
        "sys_updated_on": "2026-11-09 08:15:00",
    },
]


@pytest.fixture
def server() -> FastMCP:
    init_services(make_server_config())
    fresh = FastMCP("apps-test")
    apps.register_apps(fresh)
    return fresh


@pytest.fixture
def instance(monkeypatch: pytest.MonkeyPatch) -> Mock:
    request = Mock(
        side_effect=[sn_response({"result": HEADER}), sn_response({"result": CHANGES})]
    )
    monkeypatch.setattr(apps, "make_sn_request", request)
    return request


class TestRegistration:
    async def test_tool_names_its_view_and_is_read_only(self, server: FastMCP) -> None:
        async with Client(server) as client:
            tools = await client.list_tools()
        assert [t.name for t in tools] == [apps.REVIEW_TOOL]
        tool = tools[0]
        assert tool.meta is not None
        # The wire format a host looks for: _meta.ui.resourceUri.
        assert tool.meta["ui"] == {"resourceUri": apps.UPDATE_SET_REVIEW_URI}
        assert tool.annotations is not None and tool.annotations.read_only_hint is True
        assert tool.output_schema is not None
        assert set(tool.output_schema["required"]) == {
            "update_set",
            "count",
            "limit",
            "changes",
        }

    async def test_view_is_served_as_an_mcp_app_resource(self, server: FastMCP) -> None:
        async with Client(server) as client:
            resources = await client.list_resources()
            contents = await client.read_resource(apps.UPDATE_SET_REVIEW_URI)
        assert [str(r.uri) for r in resources] == [apps.UPDATE_SET_REVIEW_URI]
        assert resources[0].mime_type == UI_MIME
        assert contents[0].mime_type == UI_MIME
        assert contents[0].text == apps._view_html()
        assert contents[0].text.lstrip().startswith("<!doctype html>")


class TestReviewTool:
    async def test_returns_the_header_and_the_changes(
        self, server: FastMCP, instance: Mock
    ) -> None:
        async with Client(server) as client:
            result = await client.call_tool(
                apps.REVIEW_TOOL, {"update_set_sys_id": SET_ID, "limit": 50}
            )
        assert result.structured_content == {
            "update_set": HEADER,
            "count": 2,
            "limit": 50,
            "changes": CHANGES,
        }
        # A host without MCP Apps shows this text: the same data, no fallback tool.
        assert json.loads(result.content[0].text) == result.structured_content

        header_call, changes_call = instance.call_args_list
        assert header_call.args[:2] == (
            "GET",
            f"https://test.service-now.com/api/now/table/sys_update_set/{SET_ID}",
        )
        assert header_call.kwargs["params"] == {"sysparm_fields": apps._HEADER_FIELDS}
        assert changes_call.args[:2] == (
            "GET",
            "https://test.service-now.com/api/now/table/sys_update_xml",
        )
        assert changes_call.kwargs["params"] == {
            "sysparm_query": f"update_set={SET_ID}^ORDERBYDESCsys_updated_on",
            "sysparm_fields": apps._CHANGE_FIELDS,
            "sysparm_limit": 50,
        }

    async def test_only_reads(self, server: FastMCP, instance: Mock) -> None:
        async with Client(server) as client:
            await client.call_tool(apps.REVIEW_TOOL, {"update_set_sys_id": SET_ID})
        assert {call.args[0] for call in instance.call_args_list} == {"GET"}

    @pytest.mark.parametrize(
        "bad", [f"{SET_ID}^ORstate=complete", "../sys_user", "a b", ""]
    )
    async def test_refuses_an_id_that_could_rewrite_the_query(
        self, server: FastMCP, instance: Mock, bad: str
    ) -> None:
        async with Client(server) as client:
            with pytest.raises(ToolError):
                await client.call_tool(apps.REVIEW_TOOL, {"update_set_sys_id": bad})
        instance.assert_not_called()

    async def test_limit_is_capped(self, server: FastMCP, instance: Mock) -> None:
        async with Client(server) as client:
            with pytest.raises(ToolError):
                await client.call_tool(
                    apps.REVIEW_TOOL, {"update_set_sys_id": SET_ID, "limit": 201}
                )
        instance.assert_not_called()


class TestViewFile:
    """Static checks on the HTML: self-contained, escapes record text, speaks the protocol."""

    html = (
        files("servicenow_mcp.apps")
        .joinpath("update_set_review.html")
        .read_text(encoding="utf-8")
    )

    @pytest.mark.parametrize(
        "needle",
        [
            "http://",
            "https://",
            "//cdn",
            "@import",
            "src=",
            "href=",
            "fetch(",
            "XMLHttpRequest",
            "WebSocket",
            "eval(",
            "new Function",
        ],
    )
    def test_loads_and_contacts_nothing(self, needle: str) -> None:
        # A host's default policy for a view allows inline script and style only.
        assert needle not in self.html

    @pytest.mark.parametrize(
        "needle", ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"]
    )
    def test_never_writes_record_text_as_markup(self, needle: str) -> None:
        assert needle not in self.html

    @pytest.mark.parametrize(
        "needle",
        [
            '"ui/initialize"',
            "appInfo",
            "appCapabilities",
            'PROTOCOL_VERSION = "2026-01-26"',
            '"ui/notifications/initialized"',
            '"ui/notifications/tool-input"',
            '"ui/notifications/tool-result"',
            '"ui/notifications/size-changed"',
            '"ui/resource-teardown"',
            '"tools/call"',
            "event.source !== host",
        ],
    )
    def test_speaks_the_view_side_of_the_protocol(self, needle: str) -> None:
        assert needle in self.html

    def test_ships_in_the_package(self) -> None:
        assert (Path(apps.__file__).parent / "update_set_review.html").is_file()


class TestSwitch:
    def test_off_by_default(self) -> None:
        assert make_server_config().apps is False
        assert cli._apps_enabled(argparse.Namespace()) is False

    @pytest.mark.parametrize(
        ("raw", "expected"), [("on", True), (" ON ", True), ("off", False)]
    )
    def test_on_and_off(self, raw: str, expected: bool) -> None:
        assert cli._apps_enabled(argparse.Namespace(apps=raw)) is expected

    @pytest.mark.parametrize("raw", ["true", "1", "yes", ""])
    def test_any_other_value_stops_startup_without_repeating_it(self, raw: str) -> None:
        with pytest.raises(ValueError) as caught:
            cli._apps_enabled(argparse.Namespace(apps=raw))
        message = str(caught.value)
        assert "--apps must be 'on' or 'off'" in message
        assert f"{len(raw)} characters" in message
        if len(raw) > 1:  # "1" is also the length the message reports
            assert raw not in message


_PROBE = r"""
import asyncio, json, sys
from unittest.mock import patch

from fastmcp import Client

from servicenow_mcp import cli
from servicenow_mcp.server import mcp

cli.load_dotenv = lambda: None
sys.argv = ["mcp-server-servicenow", *sys.argv[1:]]
with patch("servicenow_mcp.middleware.read_only_identity.has_role", lambda *a: False), \
        patch.object(mcp, "run"):
    cli.main()

async def probe():
    async with Client(mcp) as client:
        tools = {t.name: (t.meta or {}).get("ui") for t in await client.list_tools()}
        ui = [str(r.uri) for r in await client.list_resources() if str(r.uri).startswith("ui://")]
        return {"tools": tools, "ui": ui}

print(json.dumps(asyncio.run(probe())))
"""


def _probe(tmp_path: Path, *argv: str, env: dict[str, str] | None = None) -> Any:
    clean = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("SERVICENOW_", "MCP_")) and k != "PORT"
    }
    clean.update(
        {
            # Never contacted; a closed local port all the same.
            "SERVICENOW_INSTANCE_URL": "http://127.0.0.1:9",
            "SERVICENOW_USERNAME": "probe",
            "SERVICENOW_PASSWORD": "probe",
            "SERVICENOW_AUDIT_LOG": "off",
        }
    )
    clean.update(env or {})
    done = subprocess.run(
        [sys.executable, "-I", "-B", "-c", _PROBE, *argv],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=clean,
        timeout=120,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


class TestServer:
    """main() in a fresh interpreter: what a client lists in each mode."""

    def test_default_serves_no_app(self, tmp_path: Path) -> None:
        from tests.inventory import ALL_TOOLS

        served = _probe(tmp_path)
        assert set(served["tools"]) == ALL_TOOLS
        assert not any(served["tools"].values())
        assert served["ui"] == []

    def test_on_adds_one_read_tool_and_its_view(self, tmp_path: Path) -> None:
        from tests.inventory import ALL_TOOLS

        served = _probe(tmp_path, "--apps", "on")
        assert set(served["tools"]) == ALL_TOOLS | {apps.REVIEW_TOOL}
        assert served["tools"][apps.REVIEW_TOOL] == {
            "resourceUri": apps.UPDATE_SET_REVIEW_URI
        }
        assert served["ui"] == [apps.UPDATE_SET_REVIEW_URI]

    def test_read_only_mode_keeps_the_view(self, tmp_path: Path) -> None:
        served = _probe(tmp_path, "--apps", "on", "--read-only")
        assert apps.REVIEW_TOOL in served["tools"]
        assert "create_record" not in served["tools"]
