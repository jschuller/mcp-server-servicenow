"""docs/contract.json and the generated block in docs/tools.md match what the server serves.

On failure, regenerate both with `uv run --frozen --extra dev python scripts/contract.py --write` and review the
diff: it is the change a client will see (a description, a parameter, a schema, an annotation, a resource, a
capability or an extension the server advertises, the protocol version it negotiates).

The snapshot is exact for the locked dependencies (uv.lock). CI's test matrix installs unlocked, newer versions,
where FastMCP or pydantic may render a schema differently; there the comparison is skipped, and CI's `package` job
runs the same check against the lock instead.
"""

import importlib.metadata
import importlib.util
import json
import re
import socket
import tomllib
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, List

import mcp_types
import pytest
from fastmcp import Client

from tests.conftest import init_test_services, sn_response
from tests.inventory import ALL_TOOLS

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "contract.py"
SCHEMA_PACKAGES = ("fastmcp", "fastmcp-slim", "mcp", "pydantic", "pydantic-core")


def _contract_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("contract_script", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _differs_from_lock() -> List[str]:
    lock = tomllib.loads((REPO / "uv.lock").read_text(encoding="utf-8"))
    locked = {p["name"]: p["version"] for p in lock.get("package", [])}
    out = []
    for name in SCHEMA_PACKAGES:
        try:
            installed = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            continue
        if name in locked and locked[name] != installed:
            out.append(f"{name} {installed} (lock {locked[name]})")
    return out


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Generating the contract must not open a socket or resolve a name."""

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("scripts/contract.py tried to reach the network")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def test_committed_contract_and_reference_match_the_server(no_network: None) -> None:
    drift = _differs_from_lock()
    if drift:
        pytest.skip(f"installed versions differ from uv.lock: {', '.join(drift)}")
    contract = _contract_module()
    for path, text in contract.expected().items():
        assert path.read_text(encoding="utf-8") == text, (
            f"{path.name} drifts from the server's contract; run: {contract.REGENERATE}"
        )


def test_contract_lists_every_tool_and_names_no_instance() -> None:
    contract = _contract_module()
    text = contract.CONTRACT.read_text(encoding="utf-8")
    committed = json.loads(text)
    assert {t["name"] for t in committed["tools"]} == ALL_TOOLS
    assert (
        "contract.invalid" not in text
    )  # the placeholder instance never leaks into what clients see
    assert "service-now.com" not in text


def test_contract_records_what_the_server_negotiates() -> None:
    """Both ways a client connects are in the snapshot, so a dependency bump that
    adds or drops a capability or an extension, or moves a default protocol
    version, shows up as a diff of docs/contract.json."""
    contract = _contract_module()
    negotiation = json.loads(contract.CONTRACT.read_text(encoding="utf-8"))[
        "negotiation"
    ]
    assert set(negotiation) == {"discover", "initialize"}
    discover, initialize = negotiation["discover"], negotiation["initialize"]
    assert set(discover) == {
        "protocolVersion",
        "supportedVersions",
        "serverInfo",
        "capabilities",
    }
    assert set(initialize) == {"protocolVersion", "serverInfo", "capabilities"}
    assert discover["protocolVersion"] in discover["supportedVersions"]
    for result in (discover, initialize):
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", result["protocolVersion"])
    for result in (discover, initialize):
        # The name only: the version changes with every release.
        assert result["serverInfo"] == {"name": "servicenow-mcp"}
        assert {"tools", "resources"} <= set(result["capabilities"])


async def test_initialize_asking_for_2025_03_26_negotiates_it(
    no_network: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ServiceNow's MCP client is documented at protocol version 2025-03-26.

    FastMCP's client always offers the newest handshake version, so this sends
    the initialize request itself, over the same in-process transport, and
    then uses the session at the version the server answered.
    """
    from servicenow_mcp.server import mcp
    from servicenow_mcp.tools import table_tools

    asked = "2025-03-26"
    init_test_services()
    monkeypatch.setattr(
        table_tools,
        "make_sn_request",
        lambda *args, **kwargs: sn_response({"result": [{"number": "INC0010001"}]}),
    )
    async with Client(mcp, mode="legacy", auto_initialize=False) as client:
        session = client.session
        assert session.protocol_version is None  # nothing negotiated yet
        result = await session.send_request(
            mcp_types.InitializeRequest(
                params=mcp_types.InitializeRequestParams(
                    protocol_version=asked,
                    capabilities=mcp_types.ClientCapabilities(),
                    client_info=mcp_types.Implementation(
                        name="contract-test", version="0"
                    ),
                )
            ),
            mcp_types.InitializeResult,
        )
        assert result.protocol_version == asked
        assert result.server_info.name == "servicenow-mcp"
        assert result.capabilities.tools is not None
        assert result.capabilities.resources is not None

        session.adopt(result)
        await session.send_notification(mcp_types.InitializedNotification())
        assert client.protocol_version == asked
        assert {tool.name for tool in await client.list_tools()} == ALL_TOOLS
        assert await client.list_resources()
        called = await client.call_tool(
            "list_records", {"table_name": "incident", "limit": 1}
        )
        assert called.is_error is False
        assert called.structured_content["records"] == [{"number": "INC0010001"}]


def test_contract_tools_match_the_eval_mocks() -> None:
    """Two snapshots of tools/list: the contract (through the middleware) and the eval mocks (from the tools)."""
    contract = _contract_module()
    tools: List[Dict[str, Any]] = json.loads(
        contract.CONTRACT.read_text(encoding="utf-8")
    )["tools"]
    mocks = json.loads(
        (REPO / "evals/mocks/servicenow/_tools.json").read_text(encoding="utf-8")
    )["tools"]
    assert tools == mocks


def test_generated_block_is_replaced_not_appended() -> None:
    contract = _contract_module()
    block = contract.render_reference(
        json.loads(contract.CONTRACT.read_text(encoding="utf-8"))
    )
    doc = contract.TOOLS_MD.read_text(encoding="utf-8")
    assert doc.count(contract.BEGIN) == 1 and doc.count(contract.END) == 1
    assert contract.with_reference(doc, block) == doc


def test_renderer_edge_cases() -> None:
    contract = _contract_module()
    tool = {
        "name": "t",
        "description": "a | b\nc",
        "annotations": {"readOnlyHint": False},
        "inputSchema": {
            "properties": {
                "sep": {"type": "string", "default": "a|b"},
                "either": {"type": ["string", "null"]},
                "mode": {"enum": ["x|y", "z"]},
            },
            "required": ["sep"],
        },
    }
    assert (
        contract._kind(tool) == "write, destructive"
    )  # MCP's default when destructiveHint is absent
    params = contract._params(tool)
    assert '**sep**: string = "a\\|b"' in params
    assert "either: string" in params
    assert '"x\\|y" \\| "z"' in params
    assert contract._cell(tool["description"]) == "a \\| b c"
