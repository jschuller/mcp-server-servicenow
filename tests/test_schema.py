"""fetch_table_schema: super_class walk, child-first budget, graceful degradation."""

from typing import Any, Dict, List
from unittest.mock import Mock

import pytest

from servicenow_mcp.utils.http import ServiceNowAPIError
from servicenow_mcp.utils.schema import fetch_table_schema, table_hierarchy
from tests.conftest import sn_response

API = "https://test.service-now.com/api/now"


def _dict_rows(table: str, names: List[str]) -> List[Dict[str, Any]]:
    return [
        {
            "name": table,
            "element": n,
            "column_label": n.title(),
            "internal_type": "string",
            "max_length": "40",
            "mandatory": "false",
            "reference": "",
        }
        for n in names
    ]


def _fake_sn(
    *,
    incident_fields: List[str],
    task_fields: List[str],
    db_object_error: bool = False,
) -> Mock:
    calls: List[tuple] = []

    def fake(method, url, timeout, params=None, json_data=None):
        calls.append((url, dict(params or {})))
        if "/sys_db_object" in url:
            if db_object_error:
                raise ServiceNowAPIError("403 Forbidden")
            if url.endswith("/sys_db_object"):
                return sn_response(
                    {
                        "result": [
                            {
                                "name": "incident",
                                "super_class": {"link": "l", "value": "TASKID"},
                            }
                        ]
                    }
                )
            if url.endswith("/TASKID"):
                return sn_response({"result": {"name": "task", "super_class": ""}})
        if url.endswith("/sys_dictionary"):
            query = params["sysparm_query"]
            limit = params["sysparm_limit"]
            if query.startswith("name=incident"):
                return sn_response(
                    {"result": _dict_rows("incident", incident_fields)[:limit]}
                )
            if query.startswith("name=task"):
                return sn_response({"result": _dict_rows("task", task_fields)[:limit]})
        raise AssertionError(f"unexpected call {url} {params}")

    mock = Mock(side_effect=fake)
    mock.calls = calls
    return mock


def test_hierarchy_walk_and_child_first(monkeypatch) -> None:
    mock = _fake_sn(
        incident_fields=["severity", "caller_id"],
        task_fields=["number", "short_description"],
    )
    monkeypatch.setattr("servicenow_mcp.server.make_sn_request", mock)

    result = fetch_table_schema("incident", limit=200, timeout=30, api_url=API)

    assert result["hierarchy"] == ["incident", "task"]
    assert [f["name"] for f in result["fields"]] == [
        "severity",
        "caller_id",
        "number",
        "short_description",
    ]
    assert {f["defined_in"] for f in result["fields"]} == {"incident", "task"}
    assert result["field_count"] == 4 and "truncated" not in result
    dictionary_calls = [c for c in mock.calls if c[0].endswith("/sys_dictionary")]
    assert [c[1]["sysparm_limit"] for c in dictionary_calls] == [200, 198]


def test_budget_keeps_direct_fields_and_flags_truncation(monkeypatch) -> None:
    mock = _fake_sn(incident_fields=["a", "b", "c"], task_fields=["d", "e", "f"])
    monkeypatch.setattr("servicenow_mcp.server.make_sn_request", mock)

    result = fetch_table_schema("incident", limit=4, timeout=30, api_url=API)

    assert [f["name"] for f in result["fields"]] == ["a", "b", "c", "d"]
    assert result["truncated"] is True


def test_include_inherited_false_is_one_query(monkeypatch) -> None:
    mock = _fake_sn(incident_fields=["a"], task_fields=["d"])
    monkeypatch.setattr("servicenow_mcp.server.make_sn_request", mock)

    result = fetch_table_schema(
        "incident", limit=50, timeout=30, api_url=API, include_inherited=False
    )

    assert result["hierarchy"] == ["incident"]
    assert [f["name"] for f in result["fields"]] == ["a"]
    assert "note" not in result  # not asked to walk, nothing refused
    assert len(mock.calls) == 1


def test_db_object_forbidden_degrades_to_direct_fields(monkeypatch) -> None:
    mock = _fake_sn(incident_fields=["a"], task_fields=["d"], db_object_error=True)
    monkeypatch.setattr("servicenow_mcp.server.make_sn_request", mock)

    result = fetch_table_schema("incident", limit=50, timeout=30, api_url=API)

    assert result["hierarchy"] == ["incident"]
    assert [f["name"] for f in result["fields"]] == ["a"]
    # Say so: an agent reading the hierarchy would think incident has no parent.
    assert "Parent tables could not be read" in result["note"]


def test_depth_cap_and_cycle_protection(monkeypatch) -> None:
    def fake(method, url, timeout, params=None, json_data=None):
        if url.endswith("/sys_db_object"):
            return sn_response(
                {"result": [{"name": "t0", "super_class": {"value": "ID"}}]}
            )
        # Every parent points back at itself: must stop on the cycle, not spin.
        return sn_response({"result": {"name": "t1", "super_class": {"value": "ID"}}})

    monkeypatch.setattr("servicenow_mcp.server.make_sn_request", Mock(side_effect=fake))
    assert table_hierarchy(API, "t0", 30) == ["t0", "t1"]


@pytest.mark.asyncio
async def test_tool_and_resource_share_shape(monkeypatch) -> None:
    import json

    from fastmcp import Client

    from servicenow_mcp.server import mcp
    from tests.conftest import init_test_services

    init_test_services()
    mock = _fake_sn(incident_fields=["a"], task_fields=["number"])
    monkeypatch.setattr("servicenow_mcp.server.make_sn_request", mock)
    monkeypatch.setattr("servicenow_mcp.tools.system_tools.make_sn_request", mock)

    async with Client(mcp) as client:
        tool = await client.call_tool("get_table_schema", {"table_name": "incident"})
        resource = await client.read_resource("servicenow://schema/incident")
    via_resource = json.loads(resource[0].text)
    # The tool publishes an outputSchema, so .data is a typed object; compare
    # the structured content, which is the wire JSON.
    data = tool.structured_content
    assert data["hierarchy"] == via_resource["hierarchy"] == ["incident", "task"]
    assert data["fields"][1]["defined_in"] == "task"
    assert (
        set(data)
        == set(via_resource)
        == {"table", "hierarchy", "field_count", "fields"}
    )


def test_dictionary_refusal_names_the_role(monkeypatch) -> None:
    """itil / snc_read_only callers get a 403 on sys_dictionary; say which role fixes it."""
    from servicenow_mcp import server

    def fake(method, url, timeout, params=None, json_data=None):
        raise ServiceNowAPIError("Access denied (403). The user may lack permissions")

    monkeypatch.setattr(server, "make_sn_request", fake)
    with pytest.raises(ServiceNowAPIError, match="personalize_dictionary"):
        fetch_table_schema(
            "incident", limit=10, timeout=30, api_url=API, include_inherited=False
        )


@pytest.mark.parametrize("parent", [{"name": 5}, {"label": "no name"}, None])
def test_an_unreadable_parent_is_noted(monkeypatch, parent) -> None:
    def fake(method, url, timeout, params=None, json_data=None):
        if url.endswith("/sys_db_object"):
            return sn_response(
                {"result": [{"name": "incident", "super_class": "TASKID"}]}
            )
        if url.endswith("/TASKID"):
            return sn_response({"result": parent})
        return sn_response({"result": []})

    monkeypatch.setattr("servicenow_mcp.server.make_sn_request", fake)
    result = fetch_table_schema("incident", limit=50, timeout=30, api_url=API)
    assert result["hierarchy"] == ["incident"]
    assert "Parent tables could not be read" in result["note"]
