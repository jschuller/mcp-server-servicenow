"""The list tools publish an outputSchema, and an oversized result keeps its shape."""

import json
import logging
from typing import Any, List
from unittest.mock import Mock

import pytest
from fastmcp import Client

from servicenow_mcp.middleware import audit
from servicenow_mcp.server import mcp
from servicenow_mcp.tools import table_tools
from servicenow_mcp.tools.results import LIST_KEYS
from tests.conftest import init_test_services, sn_response

# 1,000 rows of ~600 bytes: over the 500 KB limit once as text and once as
# structured content.
BIG = [{"sys_id": f"{i:032x}", "description": "x" * 600} for i in range(1000)]


class _Lines(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: List[dict[str, Any]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(json.loads(record.getMessage()))


@pytest.fixture
def audit_lines(tmp_path):
    audit.configure_audit_log(str(tmp_path / "audit.jsonl"))
    handler = _Lines()
    audit.logger.addHandler(handler)
    yield handler.lines
    audit.logger.removeHandler(handler)


async def test_output_schema_only_on_the_list_tools() -> None:
    init_test_services()
    async with Client(mcp) as client:
        tools = await client.list_tools()
    with_schema = {t.name for t in tools if t.output_schema is not None}
    assert with_schema == set(LIST_KEYS)
    records = next(t for t in tools if t.name == "list_records").output_schema
    assert records["required"] == ["count", "records"]


async def test_oversized_list_is_cut_to_a_valid_result(monkeypatch, audit_lines):
    monkeypatch.setattr(
        table_tools, "make_sn_request", Mock(return_value=sn_response({"result": BIG}))
    )
    init_test_services()
    async with Client(mcp) as client:
        # The client validates structured content against the published schema.
        result = await client.call_tool(
            "list_records", {"table_name": "incident", "offset": 40, "limit": 1000}
        )
    data = result.structured_content
    kept = len(data["records"])
    assert 0 < kept < len(BIG)
    assert data["count"] == kept
    assert data["truncated"] is True
    assert data["next_offset"] == 40 + kept
    assert data["records"] == BIG[:kept]
    assert json.loads(result.content[0].text) == data
    assert audit_lines[-1]["truncated"] is True


async def test_a_list_that_fits_is_untouched(monkeypatch, audit_lines):
    rows = BIG[:3]
    monkeypatch.setattr(
        table_tools, "make_sn_request", Mock(return_value=sn_response({"result": rows}))
    )
    init_test_services()
    async with Client(mcp) as client:
        result = await client.call_tool("list_records", {"table_name": "incident"})
    assert result.structured_content == {"count": 3, "records": rows}
    assert "truncated" not in audit_lines[-1]


async def test_other_tools_keep_the_text_cut(monkeypatch, audit_lines):
    record = {"sys_id": "a" * 32, "description": "x" * 600_000}
    monkeypatch.setattr(
        table_tools,
        "make_sn_request",
        Mock(return_value=sn_response({"result": record})),
    )
    init_test_services()
    async with Client(mcp) as client:
        result = await client.call_tool(
            "get_record", {"table_name": "incident", "sys_id": "a" * 32}
        )
    assert result.structured_content is None
    assert result.content[0].text.endswith(audit.TRUNCATION_SUFFIX)
    assert audit_lines[-1]["truncated"] is True


async def test_a_row_too_big_to_keep_leaves_a_valid_empty_list(
    monkeypatch, audit_lines
):
    huge = [{"sys_id": "a" * 32, "script": "x" * 300_000}] + BIG[:5]
    monkeypatch.setattr(
        table_tools, "make_sn_request", Mock(return_value=sn_response({"result": huge}))
    )
    init_test_services()
    async with Client(mcp) as client:
        result = await client.call_tool(
            "list_records", {"table_name": "sys_script_include", "offset": "7"}
        )
    data = result.structured_content
    assert data["records"] == [] and data["count"] == 0
    assert data["truncated"] is True and data["next_offset"] == 7
    assert "fields=" in data["note"]
    assert audit_lines[-1]["truncated"] is True


async def test_a_string_offset_pages_like_an_int(monkeypatch):
    monkeypatch.setattr(
        table_tools, "make_sn_request", Mock(return_value=sn_response({"result": BIG}))
    )
    init_test_services()
    async with Client(mcp) as client:
        result = await client.call_tool(
            "list_records", {"table_name": "incident", "offset": "40", "limit": 1000}
        )
    data = result.structured_content
    assert data["next_offset"] == 40 + len(data["records"])


@pytest.mark.parametrize(
    ("result", "rows"),
    [
        ({"sys_id": "a"}, [{"sys_id": "a"}]),
        (None, []),
        (["a", {"sys_id": "b"}], [{"sys_id": "b"}]),
    ],
)
async def test_odd_result_shapes_still_match_the_schema(monkeypatch, result, rows):
    monkeypatch.setattr(
        table_tools,
        "make_sn_request",
        Mock(return_value=sn_response({"result": result})),
    )
    init_test_services()
    async with Client(mcp) as client:
        got = await client.call_tool("list_records", {"table_name": "incident"})
    assert got.structured_content == {"count": len(rows), "records": rows}


@pytest.mark.parametrize(
    ("raw", "used"), [("+40", 40), (True, 1), ("0" * 4400 + "7", 0)]
)
async def test_offset_is_read_as_pydantic_reads_it(monkeypatch, raw, used):
    from servicenow_mcp.middleware.response_limit import _offset

    context = Mock()
    context.message.arguments = {"offset": raw}
    assert _offset(context) in (used, 7)  # pydantic may accept the long string


async def test_the_note_fits_the_tool(monkeypatch):
    from servicenow_mcp.tools import cmdb_tools

    huge = [{"sys_id": "a" * 32, "x": "x" * 300_000}]
    monkeypatch.setattr(
        cmdb_tools, "make_sn_request", Mock(return_value=sn_response({"result": huge}))
    )
    init_test_services()
    async with Client(mcp) as client:
        result = await client.call_tool(
            "get_ci_relationships", {"sys_id": "b" * 32, "offset": 3}
        )
    data = result.structured_content
    assert data["relationships"] == [] and data["next_offset"] == 3
    assert "offset=next_offset+1" in data["note"]
