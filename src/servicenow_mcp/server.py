"""ServiceNow MCP Server implementation."""

import json
import logging
from typing import Any, Dict, List, Union

import mcp.types as types
from mcp.server.lowlevel import Server
from pydantic import ValidationError

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.tool_utils import get_tool_definitions

logger = logging.getLogger(__name__)


def serialize_result(result: Any, tool_name: str) -> str:
    """Serialize tool output to a JSON string."""
    try:
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            return json.dumps(result, indent=2)
        if hasattr(result, "model_dump"):
            return json.dumps(result.model_dump(), indent=2)
        return str(result)
    except Exception as e:
        logger.error(f"Serialization error for tool '{tool_name}': {e}")
        return json.dumps({"error": f"Serialization failed: {e}"})


class ServiceNowMCP:
    """ServiceNow MCP Server - provides table, CMDB, system, and update set tools."""

    def __init__(self, config: Union[Dict, ServerConfig]) -> None:
        if isinstance(config, dict):
            self.config = ServerConfig(**config)
        else:
            self.config = config

        self.auth_manager = AuthManager(self.config.auth, self.config.instance_url)
        self.mcp_server = Server("servicenow-mcp")
        self.tool_definitions = get_tool_definitions()
        self._register_handlers()

    def _register_handlers(self) -> None:
        """Register the MCP list_tools and call_tool handlers."""
        self.mcp_server.list_tools()(self._list_tools)
        self.mcp_server.call_tool()(self._call_tool)
        logger.info(
            f"Registered {len(self.tool_definitions)} ServiceNow tools"
        )

    async def _list_tools(self) -> List[types.Tool]:
        """Return all available tools."""
        tool_list: List[types.Tool] = []
        for tool_name, (impl_func, params_model, return_type, description) in self.tool_definitions.items():
            try:
                schema = params_model.model_json_schema()
                tool_list.append(
                    types.Tool(name=tool_name, description=description, inputSchema=schema)
                )
            except Exception as e:
                logger.error(f"Failed to generate schema for '{tool_name}': {e}")
        return tool_list

    async def _call_tool(self, name: str, arguments: dict) -> list[types.TextContent]:
        """Execute a tool and return the result."""
        if name not in self.tool_definitions:
            raise ValueError(f"Unknown tool: {name}")

        impl_func, params_model, return_type, description = self.tool_definitions[name]

        # Parse and validate arguments
        try:
            params = params_model(**arguments)
        except ValidationError as e:
            raise ValueError(f"Invalid arguments for '{name}': {e}") from e

        # Execute the tool
        try:
            result = impl_func(self.config, self.auth_manager, params)
        except Exception as e:
            logger.error(f"Error executing '{name}': {e}", exc_info=True)
            raise RuntimeError(f"Error executing '{name}': {e}") from e

        # Serialize and return
        text = serialize_result(result, name)
        return [types.TextContent(type="text", text=text)]

    def start(self) -> Server:
        """Return the configured MCP Server instance for the caller to run."""
        logger.info(
            f"ServiceNow MCP server ready for {self.config.instance_url} "
            f"({len(self.tool_definitions)} tools)"
        )
        return self.mcp_server
