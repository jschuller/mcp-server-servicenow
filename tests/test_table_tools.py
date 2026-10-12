"""Tests for generic ServiceNow Table API tools."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from servicenow_mcp.tools import table_tools
from servicenow_mcp.tools.table_tools import _add_order_clause


@pytest.mark.parametrize(
    ("query", "order_by", "expected"),
    [
        ("", "sys_updated_on", "ORDERBYsys_updated_on"),
        ("", "-sys_updated_on", "ORDERBYDESCsys_updated_on"),
        (
            "active=true^priority=1",
            "-sys_updated_on",
            "active=true^priority=1^ORDERBYDESCsys_updated_on",
        ),
    ],
)
def test_add_order_clause(query: str, order_by: str, expected: str) -> None:
    assert _add_order_clause(query, order_by) == expected


def test_list_records_sends_descending_order_clause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = Mock()
    response.text = '{"result": []}'
    response.headers = {"Content-Type": "application/json"}
    response.json.return_value = {"result": []}
    make_sn_request = Mock(return_value=response)

    monkeypatch.setattr(
        table_tools,
        "get_config",
        lambda: SimpleNamespace(
            api_url="https://test.service-now.com/api/now", timeout=30
        ),
    )
    monkeypatch.setattr(table_tools, "make_sn_request", make_sn_request)

    result = table_tools.list_records(
        table_name="incident",
        query="active=true",
        fields="number,sys_updated_on",
        limit=5,
        order_by="-sys_updated_on",
    )

    assert result == {"count": 0, "records": []}
    make_sn_request.assert_called_once_with(
        "GET",
        "https://test.service-now.com/api/now/table/incident",
        30,
        params={
            "sysparm_limit": 5,
            "sysparm_offset": 0,
            "sysparm_query": "active=true^ORDERBYDESCsys_updated_on",
            "sysparm_fields": "number,sys_updated_on",
        },
    )


def _list_with_rows(
    monkeypatch: pytest.MonkeyPatch, rows: list, fields: str | None
) -> dict:
    response = Mock()
    response.text = "{}"
    response.headers = {"Content-Type": "application/json"}
    response.json.return_value = {"result": rows}
    monkeypatch.setattr(
        table_tools,
        "get_config",
        lambda: SimpleNamespace(
            api_url="https://test.service-now.com/api/now", timeout=30
        ),
    )
    monkeypatch.setattr(table_tools, "make_sn_request", Mock(return_value=response))
    return table_tools.list_records(table_name="incident", fields=fields)


def test_list_records_warns_when_a_requested_field_is_in_no_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [{"number": "INC1"}, {"number": "INC2"}]
    result = _list_with_rows(monkeypatch, rows, "number, caused_by,rfc,number")
    assert result["count"] == 2
    assert result["warning"].startswith(
        "Fields missing from every row: caused_by, rfc."
    )
    assert "incident" in result["warning"]
    assert "ACL" in result["warning"]


@pytest.mark.parametrize(
    ("rows", "fields"),
    [
        ([{"number": "INC1", "caused_by": ""}], "number,caused_by"),
        # Present in one row is enough: the field exists and is readable.
        ([{"number": "INC1"}, {"number": "INC2", "rfc": "x"}], "number,rfc"),
        # Dot-walked fields come back under their dotted name.
        ([{"caller_id.name": "Abel"}], "caller_id.name"),
        # No rows: nothing to compare against.
        ([], "number,caused_by"),
        # No fields requested: the whole readable row comes back.
        ([{"number": "INC1"}], None),
    ],
)
def test_list_records_no_warning(
    monkeypatch: pytest.MonkeyPatch, rows: list, fields: str | None
) -> None:
    result = _list_with_rows(monkeypatch, rows, fields)
    assert "warning" not in result
    assert result == {"count": len(rows), "records": rows}
