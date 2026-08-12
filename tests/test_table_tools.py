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
