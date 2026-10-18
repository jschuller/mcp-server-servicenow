"""find_references: where-used by name, never by body, one source at a time."""

from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import Mock

import pytest

from servicenow_mcp.middleware.policy import PolicyError
from servicenow_mcp.tools import system_tools
from servicenow_mcp.utils.http import ServiceNowAPIError
from tests.conftest import sn_response

BODY_FIELDS = {"script", "condition", "conditions", "filter_condition"}


@pytest.fixture
def sn(monkeypatch) -> Mock:
    def respond(method: str, url: str, timeout: int, params: Dict[str, Any]) -> Any:
        if url.endswith("/sys_security_acl"):
            raise ServiceNowAPIError(
                "Access denied (403). The user may lack permissions for this API; "
                "roles per tool: … URL: " + url
            )
        return sn_response({"result": [{"sys_id": "1", "name": url.rsplit("/", 1)[1]}]})

    mock = Mock(side_effect=respond)
    monkeypatch.setattr(system_tools, "make_sn_request", mock)
    monkeypatch.setattr(
        system_tools,
        "get_config",
        lambda: SimpleNamespace(
            api_url="https://test.service-now.com/api/now", timeout=30
        ),
    )
    return mock


def _queries(mock: Mock) -> Dict[str, Dict[str, Any]]:
    return {
        c.args[1].rsplit("/", 1)[1]: c.kwargs["params"] for c in mock.call_args_list
    }


def test_table_mode_reads_each_source_once(sn: Mock) -> None:
    report = system_tools.find_references(table_name="incident")
    queries = _queries(sn)
    assert queries["sys_script"]["sysparm_query"] == "collection=incident"
    assert queries["sys_script_client"]["sysparm_query"] == "table=incident"
    assert queries["sys_ui_policy"]["sysparm_query"] == "table=incident"
    assert (
        queries["sys_security_acl"]["sysparm_query"]
        == "name=incident^ORnameSTARTSWITHincident."
    )
    assert queries["sys_script_include"]["sysparm_query"] == "scriptLIKEincident"
    assert queries["sys_dictionary"]["sysparm_query"] == "reference=incident"
    assert len(sn.call_args_list) == 6
    assert "field" not in report
    assert [g["source"] for g in report["groups"]] == [
        "business_rules",
        "client_scripts",
        "ui_policies",
        "script_includes",
        "reference_fields",
    ]


def test_a_refused_source_is_not_assessable_not_fatal(sn: Mock) -> None:
    report = system_tools.find_references(table_name="incident")
    assert report["not_assessable"] == [
        {"source": "acls", "table": "sys_security_acl", "reason": "Access denied (403)"}
    ]


def test_field_mode_narrows_every_query(sn: Mock) -> None:
    report = system_tools.find_references(
        table_name="incident", field_name="assigned_to"
    )
    queries = _queries(sn)
    assert report["field"] == "assigned_to"
    assert queries["sys_script"]["sysparm_query"] == (
        "collection=incident^scriptLIKEassigned_to^ORconditionLIKEassigned_to"
        "^ORfilter_conditionLIKEassigned_to"
    )
    assert (
        queries["sys_script_client"]["sysparm_query"]
        == "table=incident^field=assigned_to^ORscriptLIKEassigned_to"
    )
    assert (
        queries["sys_ui_policy_action"]["sysparm_query"]
        == "table=incident^field=assigned_to"
    )
    assert (
        queries["sys_security_acl"]["sysparm_query"]
        == "name=incident.assigned_to^ORname=incident.*"
    )
    assert "sys_dictionary" not in queries and "sys_ui_policy" not in queries


@pytest.mark.parametrize("field", [None, "assigned_to"])
def test_never_asks_for_a_body(sn: Mock, field: Any) -> None:
    system_tools.find_references(table_name="incident", field_name=field)
    for params in _queries(sn).values():
        assert not BODY_FIELDS & set(params["sysparm_fields"].split(","))
        assert params["sysparm_display_value"] == "true"


def test_complete_is_false_at_the_limit(sn: Mock) -> None:
    report = system_tools.find_references(table_name="incident", limit=1)
    assert all(g["count"] == 1 and g["complete"] is False for g in report["groups"])


@pytest.mark.parametrize(
    ("table", "field"), [("incident^ORactive=true", None), ("incident", "a^ORb=1")]
)
def test_query_injection_is_refused(sn: Mock, table: str, field: Any) -> None:
    with pytest.raises(PolicyError):
        system_tools.find_references(table_name=table, field_name=field)
    sn.assert_not_called()
