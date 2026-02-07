"""Tests for tool parameter model validation."""

import pytest
from pydantic import ValidationError

from servicenow_mcp.tools.table_tools import (
    CreateRecordParams,
    DeleteRecordParams,
    GetRecordParams,
    ListRecordsParams,
    UpdateRecordParams,
)
from servicenow_mcp.tools.cmdb_tools import (
    CreateCIParams,
    GetCIParams,
    GetCIRelationshipsParams,
    ListCIParams,
    UpdateCIParams,
)
from servicenow_mcp.tools.system_tools import (
    GetCurrentUserParams,
    GetSystemPropertiesParams,
    GetTableSchemaParams,
)
from servicenow_mcp.tools.update_set_tools import (
    CreateUpdateSetParams,
    GetUpdateSetParams,
    ListUpdateSetChangesParams,
    ListUpdateSetsParams,
    SetCurrentUpdateSetParams,
)


class TestListRecordsParams:
    def test_valid_minimal(self) -> None:
        params = ListRecordsParams(table_name="incident")
        assert params.table_name == "incident"
        assert params.limit == 20
        assert params.offset == 0

    def test_valid_full(self) -> None:
        params = ListRecordsParams(
            table_name="incident",
            query="active=true",
            fields="number,short_description",
            limit=50,
            offset=10,
            order_by="-sys_created_on",
        )
        assert params.limit == 50

    def test_missing_table_name(self) -> None:
        with pytest.raises(ValidationError):
            ListRecordsParams()  # type: ignore[call-arg]

    def test_limit_too_low(self) -> None:
        with pytest.raises(ValidationError):
            ListRecordsParams(table_name="incident", limit=0)

    def test_limit_too_high(self) -> None:
        with pytest.raises(ValidationError):
            ListRecordsParams(table_name="incident", limit=1001)

    def test_negative_offset(self) -> None:
        with pytest.raises(ValidationError):
            ListRecordsParams(table_name="incident", offset=-1)


class TestGetRecordParams:
    def test_valid(self) -> None:
        params = GetRecordParams(table_name="incident", sys_id="abc123")
        assert params.sys_id == "abc123"

    def test_missing_sys_id(self) -> None:
        with pytest.raises(ValidationError):
            GetRecordParams(table_name="incident")  # type: ignore[call-arg]


class TestCreateRecordParams:
    def test_valid(self) -> None:
        params = CreateRecordParams(
            table_name="incident",
            data={"short_description": "Test"},
        )
        assert params.data["short_description"] == "Test"

    def test_missing_data(self) -> None:
        with pytest.raises(ValidationError):
            CreateRecordParams(table_name="incident")  # type: ignore[call-arg]


class TestUpdateRecordParams:
    def test_valid(self) -> None:
        params = UpdateRecordParams(
            table_name="incident",
            sys_id="abc123",
            data={"state": "2"},
        )
        assert params.sys_id == "abc123"


class TestDeleteRecordParams:
    def test_valid(self) -> None:
        params = DeleteRecordParams(table_name="incident", sys_id="abc123")
        assert params.table_name == "incident"


class TestListCIParams:
    def test_defaults(self) -> None:
        params = ListCIParams()
        assert params.class_name == "cmdb_ci"
        assert params.limit == 20

    def test_custom_class(self) -> None:
        params = ListCIParams(class_name="cmdb_ci_server")
        assert params.class_name == "cmdb_ci_server"


class TestGetCIParams:
    def test_valid(self) -> None:
        params = GetCIParams(sys_id="abc123")
        assert params.class_name == "cmdb_ci"


class TestCreateCIParams:
    def test_valid(self) -> None:
        params = CreateCIParams(data={"name": "Test Server"})
        assert params.data["name"] == "Test Server"


class TestUpdateCIParams:
    def test_valid(self) -> None:
        params = UpdateCIParams(sys_id="abc123", data={"name": "Updated"})
        assert params.sys_id == "abc123"


class TestGetCIRelationshipsParams:
    def test_valid(self) -> None:
        params = GetCIRelationshipsParams(sys_id="abc123")
        assert params.relation_type is None

    def test_with_type(self) -> None:
        params = GetCIRelationshipsParams(sys_id="abc123", relation_type="xyz")
        assert params.relation_type == "xyz"


class TestGetSystemPropertiesParams:
    def test_defaults(self) -> None:
        params = GetSystemPropertiesParams()
        assert params.query is None
        assert params.limit == 20


class TestGetCurrentUserParams:
    def test_defaults(self) -> None:
        params = GetCurrentUserParams()
        assert params.fields is None


class TestGetTableSchemaParams:
    def test_valid(self) -> None:
        params = GetTableSchemaParams(table_name="incident")
        assert params.limit == 50

    def test_missing_table_name(self) -> None:
        with pytest.raises(ValidationError):
            GetTableSchemaParams()  # type: ignore[call-arg]


class TestCreateUpdateSetParams:
    def test_valid_minimal(self) -> None:
        params = CreateUpdateSetParams(name="My Update Set")
        assert params.description is None
        assert params.parent is None

    def test_valid_full(self) -> None:
        params = CreateUpdateSetParams(
            name="My Update Set",
            description="For testing",
            parent="parent-id",
        )
        assert params.description == "For testing"

    def test_missing_name(self) -> None:
        with pytest.raises(ValidationError):
            CreateUpdateSetParams()  # type: ignore[call-arg]


class TestGetUpdateSetParams:
    def test_valid(self) -> None:
        params = GetUpdateSetParams(sys_id="abc123")
        assert params.sys_id == "abc123"


class TestSetCurrentUpdateSetParams:
    def test_valid(self) -> None:
        params = SetCurrentUpdateSetParams(sys_id="abc123")
        assert params.sys_id == "abc123"


class TestListUpdateSetsParams:
    def test_defaults(self) -> None:
        params = ListUpdateSetsParams()
        assert params.state is None
        assert params.limit == 20


class TestListUpdateSetChangesParams:
    def test_valid(self) -> None:
        params = ListUpdateSetChangesParams(update_set_sys_id="abc123")
        assert params.limit == 50

    def test_missing_sys_id(self) -> None:
        with pytest.raises(ValidationError):
            ListUpdateSetChangesParams()  # type: ignore[call-arg]
