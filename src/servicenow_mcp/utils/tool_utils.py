"""Tool definition registry for the ServiceNow MCP server."""

from typing import Any, Callable, Dict, Tuple, Type

from servicenow_mcp.tools.table_tools import (
    CreateRecordParams,
    DeleteRecordParams,
    GetRecordParams,
    ListRecordsParams,
    UpdateRecordParams,
    create_record,
    delete_record,
    get_record,
    list_records,
    update_record,
)
from servicenow_mcp.tools.cmdb_tools import (
    CreateCIParams,
    GetCIParams,
    GetCIRelationshipsParams,
    ListCIParams,
    UpdateCIParams,
    create_ci,
    get_ci,
    get_ci_relationships,
    list_ci,
    update_ci,
)
from servicenow_mcp.tools.system_tools import (
    GetCurrentUserParams,
    GetSystemPropertiesParams,
    GetTableSchemaParams,
    get_current_user,
    get_system_properties,
    get_table_schema,
)
from servicenow_mcp.tools.update_set_tools import (
    CreateUpdateSetParams,
    GetUpdateSetParams,
    ListUpdateSetChangesParams,
    ListUpdateSetsParams,
    SetCurrentUpdateSetParams,
    create_update_set,
    get_update_set,
    list_update_set_changes,
    list_update_sets,
    set_current_update_set,
)

# (impl_func, params_model, return_type, description)
ToolDefinition = Tuple[Callable, Type[Any], Type, str]


def get_tool_definitions() -> Dict[str, ToolDefinition]:
    """Returns all available ServiceNow tool definitions."""
    return {
        # Table API Tools
        "list_records": (
            list_records,
            ListRecordsParams,
            dict,
            "List records from any ServiceNow table with optional filtering, field selection, and pagination",
        ),
        "get_record": (
            get_record,
            GetRecordParams,
            dict,
            "Get a single record from a ServiceNow table by sys_id",
        ),
        "create_record": (
            create_record,
            CreateRecordParams,
            dict,
            "Create a new record in any ServiceNow table",
        ),
        "update_record": (
            update_record,
            UpdateRecordParams,
            dict,
            "Update an existing record in a ServiceNow table",
        ),
        "delete_record": (
            delete_record,
            DeleteRecordParams,
            str,
            "Delete a record from a ServiceNow table by sys_id",
        ),
        # CMDB Tools
        "list_ci": (
            list_ci,
            ListCIParams,
            dict,
            "List CMDB configuration items with optional class and query filtering",
        ),
        "get_ci": (
            get_ci,
            GetCIParams,
            dict,
            "Get a single CMDB configuration item by sys_id",
        ),
        "create_ci": (
            create_ci,
            CreateCIParams,
            dict,
            "Create a new CMDB configuration item",
        ),
        "update_ci": (
            update_ci,
            UpdateCIParams,
            dict,
            "Update a CMDB configuration item",
        ),
        "get_ci_relationships": (
            get_ci_relationships,
            GetCIRelationshipsParams,
            dict,
            "Get relationships for a CMDB configuration item (parent and child)",
        ),
        # System Tools
        "get_system_properties": (
            get_system_properties,
            GetSystemPropertiesParams,
            dict,
            "Query ServiceNow system properties",
        ),
        "get_current_user": (
            get_current_user,
            GetCurrentUserParams,
            dict,
            "Get the currently authenticated user's information",
        ),
        "get_table_schema": (
            get_table_schema,
            GetTableSchemaParams,
            dict,
            "Get the data dictionary (field definitions) for a ServiceNow table",
        ),
        # Update Set Tools
        "list_update_sets": (
            list_update_sets,
            ListUpdateSetsParams,
            dict,
            "List update sets with optional state and query filtering",
        ),
        "get_update_set": (
            get_update_set,
            GetUpdateSetParams,
            dict,
            "Get details of a specific update set by sys_id",
        ),
        "create_update_set": (
            create_update_set,
            CreateUpdateSetParams,
            dict,
            "Create a new update set for tracking customizations",
        ),
        "set_current_update_set": (
            set_current_update_set,
            SetCurrentUpdateSetParams,
            str,
            "Set an update set as the current active update set",
        ),
        "list_update_set_changes": (
            list_update_set_changes,
            ListUpdateSetChangesParams,
            dict,
            "List all customer updates (changes) within an update set",
        ),
    }
