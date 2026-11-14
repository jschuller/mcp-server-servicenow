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


def stamped(view: str, tool_name: str) -> str:
    """``view`` as add_app() serves it: the tool's name in the head, for McpApp."""
    assert view.count("<head>\n") == 1
    return view.replace(
        "<head>\n", f'<head>\n<meta name="mcp-app-tool" content="{tool_name}">\n'
    )


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
        # Served with the tool's name, so Refresh works where the host names no tool.
        assert contents[0].text == stamped(
            apps.update_set_review_view(), apps.REVIEW_TOOL
        )
        assert apps.view_problems(contents[0].text) == []
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

    async def test_a_header_that_is_not_a_record_is_an_error_that_does_not_repeat_it(
        self, server: FastMCP, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The release's rule for single-record calls (utils/records.py)."""
        request = Mock(side_effect=[sn_response({"result": "leaked-text-1234"})])
        monkeypatch.setattr(apps, "make_sn_request", request)
        async with Client(server) as client:
            with pytest.raises(ToolError) as caught:
                await client.call_tool(apps.REVIEW_TOOL, {"update_set_sys_id": SET_ID})
        assert "a string as the result" in str(caught.value)
        assert "leaked-text-1234" not in str(caught.value)
        assert request.call_count == 1  # the changes are not read after that

    def test_reads_no_payload_and_no_property_value(self) -> None:
        """What the property value guard watches is not among the fields this tool asks for."""
        asked = set(apps._HEADER_FIELDS.split(",")) | set(
            apps._CHANGE_FIELDS.split(",")
        )
        assert not asked & {"payload", "value", "remote_update_set"}
        assert not any(field.endswith((".payload", ".value")) for field in asked)

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


class TestBuiltInView:
    """The composed document: self-contained, text-safe, and it speaks the protocol."""

    document = apps.update_set_review_view()

    def test_is_self_contained_and_text_safe(self) -> None:
        # A host's default policy for a view allows inline script and style only.
        assert apps.view_problems(self.document) == []

    def test_is_one_document_with_the_shared_parts_inlined(self) -> None:
        assert self.document.startswith("<!doctype html>")
        assert self.document.count("<html") == self.document.count("</html>") == 1
        assert apps.asset("base.css") in self.document
        assert apps.asset("bridge.js") in self.document
        # The bridge is defined before the view's own script uses it.
        assert self.document.index("const McpApp =") < self.document.rindex(
            "McpApp.connect("
        )

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
            '"ui/notifications/tool-cancelled"',
            '"ui/notifications/host-context-changed"',
            '"ui/notifications/size-changed"',
            '"ui/resource-teardown"',
            '"tools/call"',
            "event.source !== host",
            # The tool's name: the host's toolInfo, else what add_app() stamped.
            "context.toolInfo",
            'meta[name="mcp-app-tool"]',
            "does not know its tool's name",
        ],
    )
    def test_bridge_speaks_the_view_side_of_the_protocol(self, needle: str) -> None:
        assert needle in apps.asset("bridge.js")

    @pytest.mark.parametrize("name", ["bridge.js", "base.css", "table_view.html"])
    def test_parts_ship_in_the_package(self, name: str) -> None:
        assert (Path(apps.__file__).parent / name).is_file()

    def test_is_a_table_view_of_the_tool_result(self) -> None:
        """The settings name fields the tool returns: a renamed field would draw an empty column."""
        config = view_config(self.document)
        assert config["rows"] == "changes"
        assert config["header"]["key"] == "update_set"
        assert config["limit"] == "limit"
        assert {"update_set", "changes", "limit"} <= set(
            apps.UpdateSetReview.__annotations__
        )
        change_fields = set(apps._CHANGE_FIELDS.split(","))
        drawn = {c["key"] for c in config["columns"]}
        drawn |= {c["sub"] for c in config["columns"] if "sub" in c}
        assert drawn | {config["facet"]} | set(config["search"]) <= change_fields
        header_fields = set(apps._HEADER_FIELDS.split(","))
        header = config["header"]
        named = {header["title"], header["badge"], header["text"]}
        named |= {d["key"] for d in header["details"]}
        assert named <= header_fields
        delete = next(c for c in config["columns"] if c["key"] == "action")
        assert delete["danger"] == ["DELETE"]


def view_config(document: str) -> Any:
    """The settings table_view() wrote into ``document``, as the view's script reads them."""
    opening = '<script type="application/json" id="view-config">'
    assert document.count(opening) == 1
    block = document.split(opening, 1)[1].split("</script>", 1)[0]
    return json.loads(block)


INCIDENT_COLUMNS: list[apps.Column] = [
    {"key": "number", "label": "Number", "nowrap": True},
    {"key": "priority", "label": "Priority", "badge": True, "danger": ["1"]},
    {"key": "short_description", "sub": "assigned_to.name", "wide": True},
]


class TestTableView:
    """``table_view()``: a view of a list from settings, with no script to write."""

    def test_writes_the_settings_into_a_self_contained_document(self) -> None:
        document = apps.table_view(
            title="Open incidents",
            rows="records",
            columns=INCIDENT_COLUMNS,
            facet="priority",
            noun=("incident", "incidents"),
        )
        assert apps.view_problems(document) == []
        assert "<title>Open incidents</title>" in document
        assert apps.asset("table_view.html") in document
        assert document.index('id="view-config"') < document.index("getElementById(id)")
        assert view_config(document) == {
            "name": "open-incidents",
            "version": __import__("servicenow_mcp").__version__,
            "title": "Open incidents",
            "rows": "records",
            "columns": [
                {"key": "number", "label": "Number", "nowrap": True},
                {
                    "key": "priority",
                    "label": "Priority",
                    "badge": True,
                    "danger": ["1"],
                },
                # No label: the key. A dot-walked field is one key, not a path.
                {
                    "key": "short_description",
                    "label": "short_description",
                    "sub": "assigned_to.name",
                    "wide": True,
                },
            ],
            # Every column's key and second line, unless search= says otherwise.
            "search": ["number", "priority", "short_description", "assigned_to.name"],
            "noun": ["incident", "incidents"],
            "empty": "No incidents.",
            "facet": "priority",
            "facetLabel": "Priority",
        }

    def test_optional_settings(self) -> None:
        config = view_config(
            apps.table_view(
                title="Changes",
                name="my-changes",
                rows="changes",
                columns=[{"key": "name"}],
                search=[],
                header={"key": "set", "title": "name"},
                limit="limit",
                empty="Nothing here.",
            )
        )
        assert config["name"] == "my-changes"
        assert config["search"] == []
        assert config["header"] == {"key": "set", "title": "name"}
        assert config["limit"] == "limit"
        assert config["empty"] == "Nothing here."
        assert config["noun"] == ["row", "rows"]
        assert "facet" not in config

    def test_a_setting_cannot_end_the_settings_block(self) -> None:
        hostile = "</script><script>alert(1)</script><!-- & -->"
        document = apps.table_view(
            title="T", rows="records", columns=[{"key": "name", "label": hostile}]
        )
        assert hostile not in document
        assert (
            document.count("</script>")
            == apps.compose_view(apps.asset("table_view.html"), title="T").count(
                "</script>"
            )
            + 1
        )
        # The script still reads the label as it was written.
        assert view_config(document)["columns"][0]["label"] == hostile
        assert apps.view_problems(document) == []

    @pytest.mark.parametrize(
        ("change", "message"),
        [
            ({"columns": []}, "columns must be a non-empty list"),
            ({"columns": [{"label": "Name"}]}, "column 1 needs a key"),
            (
                {"columns": [{"key": "a"}, {"key": "b", "lable": "B"}]},
                "column 2 has unknown options ['lable']",
            ),
            ({"columns": [{"key": "a", "danger": "DELETE"}]}, "danger must be a list"),
            ({"columns": [{"key": "a", "wide": "yes"}]}, "wide must be True or False"),
            ({"columns": "name"}, "columns must be a non-empty list"),
            ({"rows": ""}, "rows must be a non-empty string"),
            ({"title": " "}, "title must be a non-empty string"),
            ({"search": "name"}, "search must be a list"),
            ({"noun": "incident"}, "noun is (singular, plural)"),
            ({"header": {"title": "name"}}, "header needs a key"),
            (
                {"header": {"key": "set", "heading": "name"}},
                "header has unknown options",
            ),
            (
                {"header": {"key": "set", "details": [{"key": "a"}]}},
                "a header detail is",
            ),
        ],
    )
    def test_a_wrong_setting_stops_at_once(
        self, change: dict[str, Any], message: str
    ) -> None:
        settings: dict[str, Any] = {
            "title": "T",
            "rows": "records",
            "columns": [{"key": "name"}],
        }
        with pytest.raises(ValueError) as caught:
            apps.table_view(**{**settings, **change})
        assert message in str(caught.value)

    @pytest.mark.parametrize(
        "needle",
        [
            # Drawn as text only, from the settings block, through the host.
            'JSON.parse($("view-config").textContent)',
            "McpApp.errorText(result)",
            "McpApp.data(result)",
            "app.callTool()",
            "app.canCallTools",
            "config.empty",
        ],
    )
    def test_fragment_reads_the_settings_and_the_result(self, needle: str) -> None:
        assert needle in apps.asset("table_view.html")

    async def test_goes_straight_to_add_app(self) -> None:
        """The example in docs/apps.md: a list tool, a table_view, add_app."""

        def open_incidents(limit: int = 25) -> dict[str, Any]:
            """List open incidents, highest priority first."""
            return {"records": [{"number": "INC0010001", "priority": "1"}], "count": 1}

        view = apps.table_view(
            title="Open incidents", rows="records", columns=INCIDENT_COLUMNS
        )
        mine = FastMCP("mine")
        apps.add_app(
            mine, open_incidents, uri="ui://mine/open-incidents.html", view=view
        )
        async with Client(mine) as client:
            tool = (await client.list_tools())[0]
            contents = await client.read_resource("ui://mine/open-incidents.html")
        assert tool.meta is not None
        assert tool.meta["ui"] == {"resourceUri": "ui://mine/open-incidents.html"}
        assert contents[0].text == stamped(view, "open_incidents")


class TestReusableParts:
    """What a server that imports this package builds its own view from (docs/apps.md)."""

    def test_compose_view_escapes_the_title(self) -> None:
        document = apps.compose_view("<p>hi</p>", title="A <b> & c")
        assert "<title>A &lt;b&gt; &amp; c</title>" in document
        assert "<p>hi</p>" in document
        assert apps.view_problems(document) == []

    @pytest.mark.parametrize(
        ("fragment", "reason"),
        [
            ('<script src="https://cdn.example/x.js"></script>', "names a URL"),
            ('<link rel="stylesheet" href="x.css">', "loads a file"),
            ("<style>@import 'x.css';</style>", "loads a file"),
            ("<script>fetch('/api')</script>", "opens a network connection"),
            ("<script>new WebSocket(u)</script>", "opens a network connection"),
            ("<script>n.innerHTML = row.name</script>", "writes text as markup"),
            ("<script>eval(code)</script>", "evaluates a string as code"),
        ],
    )
    def test_view_problems_names_what_is_wrong(
        self, fragment: str, reason: str
    ) -> None:
        problems = apps.view_problems(apps.compose_view(fragment, title="t"))
        assert any(reason in problem for problem in problems), problems
        assert all(problem.startswith("line ") for problem in problems)

    async def test_add_app_registers_a_custom_tool_and_its_view(self) -> None:
        """The example in docs/apps.md, in miniature."""

        def open_incidents_by_priority() -> dict[str, Any]:
            """Count open incidents per priority."""
            return {"groups": [{"priority": "1", "count": 3}]}

        view = apps.compose_view(
            '<h1>Open incidents by priority</h1><div id="rows"></div>'
            "<script>McpApp.connect({name: 'by-priority', onResult(result) {"
            " for (const g of McpApp.data(result).groups)"
            " document.getElementById('rows').append("
            "McpApp.el('p', null, g.priority + ': ' + g.count)); }});</script>",
            title="Open incidents by priority",
        )
        assert apps.view_problems(view) == []

        mine = FastMCP("mine")
        apps.add_app(
            mine,
            open_incidents_by_priority,
            uri="ui://mine/by-priority.html",
            view=view,
            tags={"read"},
        )
        async with Client(mine) as client:
            tool = (await client.list_tools())[0]
            resource = (await client.list_resources())[0]
            contents = await client.read_resource("ui://mine/by-priority.html")
            result = await client.call_tool("open_incidents_by_priority", {})
        assert tool.name == "open_incidents_by_priority"
        assert tool.description == "Count open incidents per priority."
        assert tool.meta is not None
        assert tool.meta["ui"] == {"resourceUri": "ui://mine/by-priority.html"}
        assert tool.annotations is not None and tool.annotations.read_only_hint is True
        assert resource.mime_type == UI_MIME
        assert contents[0].text == stamped(view, "open_incidents_by_priority")
        assert result.structured_content == {"groups": [{"priority": "1", "count": 3}]}

    def test_add_app_refuses_a_uri_outside_ui(self) -> None:
        with pytest.raises(ValueError, match="ui://"):
            apps.add_app(
                FastMCP("mine"), lambda: {}, uri="https://example.test/v.html", view=""
            )

    def test_add_app_refuses_a_view_that_is_not_self_contained(self) -> None:
        """A host shows such a view as an empty frame; registration says why instead."""
        view = apps.compose_view(
            '<script src="https://cdn.example/x.js"></script>'
            "<script>n.innerHTML = row.name</script>",
            title="t",
        )
        mine = FastMCP("mine")
        with pytest.raises(ValueError) as caught:
            apps.add_app(mine, lambda: {}, uri="ui://mine/v.html", view=view)
        message = str(caught.value)
        assert "ui://mine/v.html is not self-contained and text-safe" in message
        assert "names a URL" in message and "writes text as markup" in message

    def test_add_app_passes_write_annotations_through(self) -> None:
        from servicenow_mcp.tools.annotations import CREATE

        mine = FastMCP("mine")

        def create_thing() -> dict[str, Any]:
            """Create a thing."""
            return {}

        # A tool that writes carries its own annotations and the write tag,
        # so read-only mode hides it like any other write tool.
        apps.add_app(
            mine,
            create_thing,
            uri="ui://mine/create.html",
            view="<!doctype html>",
            tags={"write"},
            annotations=CREATE,
        )


class TestMount:
    """``parent.mount(server, namespace="snow")``: the tool must name the view the parent serves.

    FastMCP's namespace renames the resource (``ui://servicenow/x`` becomes
    ``ui://snow/servicenow/x``) and the tool, and copies the tool's ``_meta``
    as it is. So the server is told the namespace when the views are
    registered, like ``render_instructions("snow")``.
    """

    MOUNTED_URI = "ui://snow/servicenow/update-set-review.html"

    @staticmethod
    def _mounted(namespace: str | None, *, told: str | None) -> FastMCP:
        init_services(make_server_config())
        child = FastMCP("servicenow")
        apps.register_apps(child, namespace=told)
        parent = FastMCP("orchestrator")
        parent.mount(child, namespace=namespace)
        return parent

    async def test_a_host_finds_the_view_through_the_parent(
        self, instance: Mock
    ) -> None:
        parent = self._mounted("snow", told="snow")
        async with Client(parent) as client:
            tool = (await client.list_tools())[0]
            served = {str(r.uri): r for r in await client.list_resources()}
            # What a host does: read the URI the tool names, then call the tool.
            assert tool.meta is not None
            named = tool.meta["ui"]["resourceUri"]
            contents = await client.read_resource(named)
            result = await client.call_tool(tool.name, {"update_set_sys_id": SET_ID})
        assert tool.name == f"snow_{apps.REVIEW_TOOL}"
        assert named == self.MOUNTED_URI
        assert set(served) == {self.MOUNTED_URI}
        assert served[named].mime_type == UI_MIME
        assert contents[0].mime_type == UI_MIME
        # The view calls the tool by the name the parent gives it.
        assert contents[0].text == stamped(
            apps.update_set_review_view(), f"snow_{apps.REVIEW_TOOL}"
        )
        assert result.structured_content is not None
        assert result.structured_content["count"] == 2

    async def test_no_namespace_needs_nothing(self) -> None:
        parent = self._mounted(None, told=None)
        async with Client(parent) as client:
            tool = (await client.list_tools())[0]
            served = {str(r.uri) for r in await client.list_resources()}
        assert tool.meta is not None
        assert tool.meta["ui"] == {"resourceUri": apps.UPDATE_SET_REVIEW_URI}
        assert served == {apps.UPDATE_SET_REVIEW_URI}

    async def test_fastmcp_still_leaves_the_link_to_us(self) -> None:
        """Why ``namespace=`` exists. If this fails after a FastMCP upgrade, the
        mount rewrites ``_meta.ui.resourceUri`` itself: passing the namespace
        would then prefix it twice, so remove the parameter."""
        parent = self._mounted("snow", told=None)
        async with Client(parent) as client:
            tool = (await client.list_tools())[0]
            served = {str(r.uri) for r in await client.list_resources()}
        assert tool.meta is not None
        assert tool.meta["ui"] == {"resourceUri": apps.UPDATE_SET_REVIEW_URI}
        assert served == {self.MOUNTED_URI}

    async def test_add_app_takes_the_namespace_too(self) -> None:
        child = FastMCP("mine")

        def by_priority() -> dict[str, Any]:
            """Count open incidents per priority."""
            return {"groups": []}

        apps.add_app(
            child,
            by_priority,
            uri="ui://mine/by-priority.html",
            view="<!doctype html>",
            namespace="team",
        )
        parent = FastMCP("orchestrator")
        parent.mount(child, namespace="team")
        async with Client(parent) as client:
            tool = (await client.list_tools())[0]
            contents = await client.read_resource("ui://team/mine/by-priority.html")
        assert tool.meta is not None
        assert tool.meta["ui"] == {"resourceUri": "ui://team/mine/by-priority.html"}
        assert contents[0].text == "<!doctype html>"


UI_EXTENSION = "io.modelcontextprotocol/ui"


class TestEveryClientGetsTheSame:
    """Nothing here depends on what a client says it supports.

    Since MCP 2026-07-28 a list does not vary per connection, and a client's
    capabilities arrive per request, so a server cannot register a view tool
    only for hosts that render views. The link is static, and the result is
    useful as text.
    """

    async def test_a_client_that_declares_nothing_gets_the_link_and_the_data(
        self, server: FastMCP, instance: Mock
    ) -> None:
        async with Client(server) as client:
            tool = (await client.list_tools())[0]
            result = await client.call_tool(tool.name, {"update_set_sys_id": SET_ID})
        assert tool.meta is not None and "ui" in tool.meta
        # The deprecated flat key is not sent.
        assert "ui/resourceUri" not in tool.meta
        assert result.structured_content is not None
        assert json.loads(result.content[0].text) == result.structured_content

    def test_no_code_here_asks_what_the_client_supports(self) -> None:
        source = Path(apps.__file__).read_text(encoding="utf-8")
        assert "client_supports" not in source
        assert "get_context" not in source

    async def test_a_server_with_views_advertises_the_extension(
        self, server: FastMCP
    ) -> None:
        async with Client(server) as client:
            capabilities = client.server_capabilities
        assert capabilities is not None
        assert UI_EXTENSION in (capabilities.extensions or {})

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "FastMCP before 4.2.0 advertises the extension on every server "
            "(PrefectHQ/fastmcp#4919, fixed by #5062). When the lock moves and "
            "this passes, remove the mark and the line in docs/apps.md (Limits)."
        ),
    )
    async def test_a_server_without_views_does_not(self) -> None:
        async with Client(FastMCP("no-apps")) as client:
            capabilities = client.server_capabilities
        assert capabilities is not None
        assert UI_EXTENSION not in (capabilities.extensions or {})


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
        assert "SERVICENOW_APPS (--apps) must be 'on' or 'off'" in message
        assert f"{len(raw)} characters" in message
        if len(raw) > 1:  # "1" is also the length the message reports
            assert raw not in message

    def test_env_and_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        argv = ["mcp-server-servicenow"]
        monkeypatch.delenv("SERVICENOW_APPS", raising=False)
        monkeypatch.setattr("sys.argv", argv)
        assert cli.parse_args().apps == "off"
        monkeypatch.setenv("SERVICENOW_APPS", "on")
        assert cli.parse_args().apps == "on"
        # An empty variable, or one Claude Code passed through unset, is the default.
        monkeypatch.setenv("SERVICENOW_APPS", "")
        assert cli.parse_args().apps == "off"
        monkeypatch.setenv("SERVICENOW_APPS", "${SERVICENOW_APPS}")
        assert cli.parse_args().apps == "off"
        monkeypatch.setenv("SERVICENOW_APPS", "on")
        monkeypatch.setattr("sys.argv", [*argv, "--apps", "off"])
        assert cli.parse_args().apps == "off"


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

    def test_the_variable_turns_it_on_and_the_flag_wins(self, tmp_path: Path) -> None:
        served = _probe(tmp_path, env={"SERVICENOW_APPS": "on"})
        assert served["ui"] == [apps.UPDATE_SET_REVIEW_URI]
        served = _probe(tmp_path, "--apps", "off", env={"SERVICENOW_APPS": "on"})
        assert served["ui"] == []
        assert apps.REVIEW_TOOL not in served["tools"]

    def test_read_only_mode_keeps_the_view(self, tmp_path: Path) -> None:
        served = _probe(tmp_path, "--apps", "on", "--read-only")
        assert apps.REVIEW_TOOL in served["tools"]
        assert "create_record" not in served["tools"]
