"""Tool registry regression tests.

Safety net to ensure all 18 tools remain registered before FastMCP migration.
"""

from servicenow_mcp.utils.tool_utils import get_tool_definitions


EXPECTED_TOOLS = {
    # Table API (5)
    "list_records",
    "get_record",
    "create_record",
    "update_record",
    "delete_record",
    # CMDB (5)
    "list_ci",
    "get_ci",
    "create_ci",
    "update_ci",
    "get_ci_relationships",
    # System (3)
    "get_system_properties",
    "get_current_user",
    "get_table_schema",
    # Update Sets (5)
    "list_update_sets",
    "get_update_set",
    "create_update_set",
    "set_current_update_set",
    "list_update_set_changes",
}


class TestToolRegistry:
    def test_exact_tool_count(self) -> None:
        """Exactly 18 tools must be registered."""
        tools = get_tool_definitions()
        assert len(tools) == 18, f"Expected 18 tools, got {len(tools)}: {sorted(tools.keys())}"

    def test_all_expected_tools_present(self) -> None:
        """Every expected tool name must be in the registry."""
        tools = get_tool_definitions()
        registered = set(tools.keys())
        missing = EXPECTED_TOOLS - registered
        assert not missing, f"Missing tools: {missing}"

    def test_no_unexpected_tools(self) -> None:
        """No tools beyond the expected 18."""
        tools = get_tool_definitions()
        registered = set(tools.keys())
        extra = registered - EXPECTED_TOOLS
        assert not extra, f"Unexpected tools: {extra}"

    def test_all_tools_have_callable_impl(self) -> None:
        """Every tool definition must have a callable implementation."""
        tools = get_tool_definitions()
        for name, (impl, params_model, return_type, description) in tools.items():
            assert callable(impl), f"Tool '{name}' impl is not callable"

    def test_all_tools_have_description(self) -> None:
        """Every tool must have a non-empty description."""
        tools = get_tool_definitions()
        for name, (impl, params_model, return_type, description) in tools.items():
            assert description, f"Tool '{name}' has no description"
