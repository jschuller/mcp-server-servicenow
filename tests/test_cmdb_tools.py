"""CMDB tool behaviour that skills rely on."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from servicenow_mcp.tools import cmdb_tools
from tests.conftest import sn_response


@pytest.fixture
def cfg(monkeypatch) -> Mock:
    mock = Mock(return_value=sn_response({"result": [{"sys_id": "r1"}]}))
    monkeypatch.setattr(
        cmdb_tools,
        "get_config",
        lambda: SimpleNamespace(
            api_url="https://test.service-now.com/api/now", timeout=30
        ),
    )
    monkeypatch.setattr(cmdb_tools, "make_sn_request", mock)
    return mock


def test_get_ci_relationships_default_limit_is_100(cfg: Mock) -> None:
    result = cmdb_tools.get_ci_relationships(sys_id="abc")
    assert result == {"count": 1, "relationships": [{"sys_id": "r1"}]}
    cfg.assert_called_once_with(
        "GET",
        "https://test.service-now.com/api/now/table/cmdb_rel_ci",
        30,
        params={
            "sysparm_query": "parent=abc^ORchild=abc",
            "sysparm_limit": 100,
            "sysparm_offset": 0,
        },
    )


def test_get_ci_relationships_paging_and_type(cfg: Mock) -> None:
    cmdb_tools.get_ci_relationships(
        sys_id="abc", relation_type="t1", limit=5, offset=10
    )
    params = cfg.call_args.kwargs["params"]
    assert params == {
        "sysparm_query": "parent=abc^ORchild=abc^type=t1",
        "sysparm_limit": 5,
        "sysparm_offset": 10,
    }


@pytest.mark.asyncio
async def test_get_ci_relationships_schema_bounds() -> None:
    from fastmcp import Client

    from servicenow_mcp.server import mcp
    from tests.conftest import init_test_services

    init_test_services()
    async with Client(mcp) as client:
        tools = {t.name: t for t in await client.list_tools()}
    props = tools["get_ci_relationships"].input_schema["properties"]
    assert props["limit"]["default"] == 100 and props["limit"]["maximum"] == 1000
    assert props["offset"]["default"] == 0


@pytest.mark.parametrize(
    ("response_format", "extra"),
    [("detailed", {}), ("concise", {"sysparm_exclude_reference_link": "true"})],
)
def test_list_ci_response_format(cfg: Mock, response_format: str, extra: dict) -> None:
    cmdb_tools.list_ci(class_name="cmdb_ci_server", response_format=response_format)
    assert cfg.call_args.kwargs["params"] == {
        "sysparm_limit": 20,
        "sysparm_offset": 0,
        **extra,
    }
