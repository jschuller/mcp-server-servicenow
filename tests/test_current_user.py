"""The caller's identity and the caller-scoped update-set preference."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastmcp import Client

from servicenow_mcp import resources, server
from servicenow_mcp.server import mcp
from servicenow_mcp.tools import update_set_tools
from servicenow_mcp.utils.http import ServiceNowAPIError
from servicenow_mcp.utils.user import fetch_current_user, has_role
from tests.conftest import init_test_services, sn_response

API = "https://test.service-now.com/api/now"
ADMIN_ROW = {
    "user_name": "admin",
    "name": "System Administrator",
    "email": "admin@example.com",
    "sys_id": "u-1",
    "department": "IT",
}
ROLE_ROWS = {"result": [{"role.name": "admin"}, {"role.name": ""}]}


class TestFetchCurrentUser:
    def test_standard_keys_from_sys_user(self, monkeypatch) -> None:
        mock = Mock(
            side_effect=[
                sn_response({"result": [ADMIN_ROW]}),
                sn_response(ROLE_ROWS),
            ]
        )
        monkeypatch.setattr(server, "make_sn_request", mock)

        user = fetch_current_user(API, 30)

        assert user == {
            "user_name": "admin",
            "user_display_name": "System Administrator",
            "user_email": "admin@example.com",
            "user_sys_id": "u-1",
            "roles": ["admin"],
        }
        params = mock.call_args_list[0].kwargs["params"]
        assert params["sysparm_query"] == "user_name=javascript:gs.getUserName()"
        assert params["sysparm_fields"] == "user_name,name,email,sys_id"

    def test_roles_are_the_callers_direct_active_grants(self, monkeypatch) -> None:
        """sys_user.roles is empty for most users; roles come from the role table."""
        mock = Mock(
            side_effect=[
                sn_response({"result": [ADMIN_ROW]}),
                sn_response(ROLE_ROWS),
            ]
        )
        monkeypatch.setattr(server, "make_sn_request", mock)

        fetch_current_user(API, 30)

        url = mock.call_args_list[1].args[1]
        params = mock.call_args_list[1].kwargs["params"]
        assert url == f"{API}/table/sys_user_has_role"
        assert params["sysparm_query"] == (
            "user=javascript:gs.getUserID()^state=active^inherited=false"
        )
        assert params["sysparm_fields"] == "role.name"

    def test_unreadable_roles_are_none(self, monkeypatch) -> None:
        mock = Mock(
            side_effect=[
                sn_response({"result": [ADMIN_ROW]}),
                ServiceNowAPIError("Access denied (403)"),
            ]
        )
        monkeypatch.setattr(server, "make_sn_request", mock)

        user = fetch_current_user(API, 30)

        assert user["user_name"] == "admin"
        assert user["roles"] is None

    def test_extra_fields_are_requested_and_returned(self, monkeypatch) -> None:
        mock = Mock(return_value=sn_response({"result": [ADMIN_ROW]}))
        monkeypatch.setattr(server, "make_sn_request", mock)

        user = fetch_current_user(API, 30, fields="department, email", with_roles=False)

        assert user["department"] == "IT"
        assert user["user_email"] == "admin@example.com"
        assert "email" not in user
        assert "roles" not in user
        mock.assert_called_once()
        fields = mock.call_args.kwargs["params"]["sysparm_fields"]
        assert fields == "user_name,name,email,sys_id,department"

    def test_unreadable_row_returns_empty(self, monkeypatch) -> None:
        monkeypatch.setattr(
            server, "make_sn_request", Mock(return_value=sn_response({"result": []}))
        )
        assert fetch_current_user(API, 30) == {}


@pytest.fixture
def us_mock(monkeypatch) -> Mock:
    """One mock for the tool's own requests and fetch_current_user's."""
    mock = Mock()
    monkeypatch.setattr(
        update_set_tools,
        "get_config",
        lambda: SimpleNamespace(api_url=API, timeout=30),
    )
    monkeypatch.setattr(update_set_tools, "make_sn_request", mock)
    monkeypatch.setattr(server, "make_sn_request", mock)
    return mock


IN_PROGRESS = {"result": {"name": "Release 1", "state": "in progress"}}


class TestHasRole:
    def test_one_existence_query_filtered_to_the_caller(self, monkeypatch) -> None:
        mock = Mock(return_value=sn_response({"result": [{"sys_id": "r-1"}]}))
        monkeypatch.setattr(server, "make_sn_request", mock)

        assert has_role(API, 5, "snc_read_only") is True

        mock.assert_called_once()
        method, url, timeout = mock.call_args.args
        params = mock.call_args.kwargs["params"]
        assert (method, url, timeout) == ("GET", f"{API}/table/sys_user_has_role", 5)
        assert params == {
            "sysparm_query": (
                "user=javascript:gs.getUserID()^state=active^role.name=snc_read_only"
            ),
            "sysparm_fields": "sys_id",
            "sysparm_limit": 1,
        }

    def test_no_row_is_false(self, monkeypatch) -> None:
        monkeypatch.setattr(
            server, "make_sn_request", Mock(return_value=sn_response({"result": []}))
        )
        assert has_role(API, 5, "snc_read_only") is False

    def test_failure_is_none(self, monkeypatch) -> None:
        monkeypatch.setattr(
            server, "make_sn_request", Mock(side_effect=ServiceNowAPIError("timeout"))
        )
        assert has_role(API, 5, "snc_read_only") is None

    def test_role_name_cannot_extend_the_query(self, monkeypatch) -> None:
        mock = Mock()
        monkeypatch.setattr(server, "make_sn_request", mock)
        assert has_role(API, 5, "itil^NQrole.name=admin") is None
        mock.assert_not_called()


class TestSetCurrentUpdateSet:
    def test_patches_only_the_callers_row(self, us_mock: Mock) -> None:
        us_mock.side_effect = [
            sn_response(IN_PROGRESS),
            sn_response({"result": [{"sys_id": "pref-mine"}]}),
            sn_response({"result": {}}),
        ]

        update_set_tools.set_current_update_set(sys_id="us-1")

        lookup = us_mock.call_args_list[1]
        assert lookup.kwargs["params"]["sysparm_query"] == (
            "name=sys_update_set^user=javascript:gs.getUserID()"
        )
        method, url = us_mock.call_args_list[2].args[:2]
        assert method == "PATCH"
        assert url.endswith("/sys_user_preference/pref-mine")

    def test_new_preference_belongs_to_the_caller(self, us_mock: Mock) -> None:
        us_mock.side_effect = [
            sn_response(IN_PROGRESS),
            sn_response({"result": []}),
            sn_response({"result": [ADMIN_ROW]}),
            sn_response({"result": {}}),
        ]

        update_set_tools.set_current_update_set(sys_id="us-1")

        post = us_mock.call_args_list[3]
        assert post.args[0] == "POST"
        # Never a blank user: that row would be every user's default.
        assert post.kwargs["json_data"] == {
            "name": "sys_update_set",
            "value": "us-1",
            "user": "u-1",
        }

    def test_refuses_without_a_readable_caller(self, us_mock: Mock) -> None:
        us_mock.side_effect = [
            sn_response(IN_PROGRESS),
            sn_response({"result": []}),
            sn_response({"result": []}),
        ]

        with pytest.raises(ServiceNowAPIError, match="sys_user record"):
            update_set_tools.set_current_update_set(sys_id="us-1")
        assert [c.args[0] for c in us_mock.call_args_list] == ["GET", "GET", "GET"]


async def test_current_update_set_resource_reads_the_callers_row(monkeypatch) -> None:
    init_test_services()
    mock = Mock(
        side_effect=[
            sn_response({"result": [{"value": "us-1"}]}),
            sn_response({"result": {"sys_id": "us-1", "name": "Release 1"}}),
        ]
    )
    monkeypatch.setattr(resources, "make_sn_request", mock)

    async with Client(mcp) as client:
        content = await client.read_resource("servicenow://update-set/current")

    assert json.loads(content[0].text)["name"] == "Release 1"
    assert mock.call_args_list[0].kwargs["params"]["sysparm_query"] == (
        "name=sys_update_set^user=javascript:gs.getUserID()"
    )
