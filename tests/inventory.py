"""The registered tools, in one place: every test that counts tools uses these.

Adding a tool means adding its name here (READ_TOOLS or WRITE_TOOLS by its
``read``/``write`` tag); the counts in the other tests follow.
"""

READ_TOOLS = frozenset(
    {
        # Table API
        "list_records",
        "get_record",
        "aggregate_records",
        # CMDB
        "list_ci",
        "get_ci",
        "get_ci_relationships",
        # System
        "get_system_properties",
        "get_current_user",
        "get_table_schema",
        "find_references",
        # Update sets
        "list_update_sets",
        "get_update_set",
        "list_update_set_changes",
    }
)

WRITE_TOOLS = frozenset(
    {
        "create_record",
        "update_record",
        "delete_record",
        "create_ci",
        "update_ci",
        "create_update_set",
        "set_current_update_set",
    }
)

ALL_TOOLS = READ_TOOLS | WRITE_TOOLS
