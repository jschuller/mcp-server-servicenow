"""End-to-end smoke over a real stdio subprocess against a live PDI.

Complements the pytest suites: exercises the actual server process (CLI flags,
audit file, both protocol eras) the way a real MCP client does. Credentials
come from .env.test. Creates and deletes scratch incidents on the instance.

Run: .venv/bin/python scripts/stdio_smoke.py
"""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

from dotenv import dotenv_values
from fastmcp import Client
from fastmcp.client.elicitation import ElicitResult
from fastmcp.client.transports import StdioTransport
from fastmcp.exceptions import ToolError

REPO = str(Path(__file__).resolve().parents[1])
PY = f"{REPO}/.venv/bin/python"
creds = {k: v for k, v in dotenv_values(f"{REPO}/.env.test").items() if v}
creds["SERVICENOW_AUTH_TYPE"] = "basic"


def transport(*flags):
    env = {**os.environ, **creds}
    return StdioTransport(PY, ["-m", "servicenow_mcp.cli", *flags], env=env, cwd=REPO)


def ok(label, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + label + (f"  [{extra}]" if extra else ""))
    return cond


async def main():
    results = []
    audit = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False).name

    # A. read-only
    async with Client(transport("--read-only", "--audit-log", "off")) as c:
        tools = await c.list_tools()
        results.append(ok("read-only: 12 tools listed", len(tools) == 12, str(len(tools))))
        ann = {t.name: t.annotations for t in tools}
        results.append(
            ok(
                "annotations on wire",
                ann["list_records"] is not None
                and ann["list_records"].read_only_hint is True,
            )
        )
        try:
            await c.call_tool("delete_record", {"table_name": "incident", "sys_id": "x"})
            results.append(ok("read-only: delete_record hidden", False))
        except ToolError as e:
            results.append(
                ok("read-only: delete_record -> Unknown tool", "Unknown tool" in str(e))
            )

    # B. default mode + denylist + audit file + JS policy + schema + scratch CRUD
    async with Client(transport("--table-denylist", "sys_user*", "--audit-log", audit)) as c:
        tools = await c.list_tools()
        results.append(ok("default: 19 tools", len(tools) == 19, str(len(tools))))
        try:
            await c.call_tool("list_records", {"table_name": "sys_user", "limit": 1})
            results.append(ok("denylist blocks sys_user", False))
        except ToolError as e:
            results.append(ok("denylist blocks sys_user", "DENYLIST" in str(e)))
        try:
            await c.call_tool(
                "list_records",
                {
                    "table_name": "incident",
                    "query": "caller_id=javascript:gs.getUserID()",
                    "limit": 1,
                },
            )
            results.append(ok("JS policy rejects gs.getUserID()", False))
        except ToolError as e:
            results.append(
                ok("JS policy rejects gs.getUserID()", "unsafe javascript" in str(e))
            )
        r = await c.call_tool(
            "list_records",
            {
                "table_name": "incident",
                "query": "sys_created_on>=javascript:gs.daysAgo(3650)",
                "limit": 1,
            },
        )
        results.append(ok("JS policy allows gs.daysAgo()", "records" in r.data))
        schema = (await c.call_tool("get_table_schema", {"table_name": "incident"})).data
        by_name = {f["name"]: f for f in schema["fields"]}
        results.append(
            ok(
                "schema: incident inherits task.number",
                by_name.get("number", {}).get("defined_in") == "task",
                f"hierarchy={schema['hierarchy']} fields={schema['field_count']}",
            )
        )
        rel = await c.call_tool("get_ci_relationships", {"sys_id": "0" * 32, "limit": 5})
        results.append(ok("get_ci_relationships paging arg accepted", rel.data["count"] == 0))
        created = (
            await c.call_tool(
                "create_record",
                {
                    "table_name": "incident",
                    "data": {
                        "short_description": "mcp-server-servicenow stdio smoke (safe to delete)",
                        "impact": "3",
                        "urgency": "3",
                    },
                },
            )
        ).data
        sid = created["sys_id"]
        results.append(ok("create scratch incident", bool(sid), created["record"].get("number")))
        upd = (
            await c.call_tool(
                "update_record",
                {"table_name": "incident", "sys_id": sid, "data": {"urgency": "2"}},
            )
        ).data
        results.append(
            ok(
                "default: update_record single call, no prompt",
                upd["record"].get("urgency") == "2",
            )
        )
        dele = (
            await c.call_tool("delete_record", {"table_name": "incident", "sys_id": sid})
        ).data
        results.append(
            ok(
                "default: delete_record returns dict",
                dele == {"deleted": True, "table": "incident", "sys_id": sid},
            )
        )
    lines = [json.loads(line) for line in open(audit).read().splitlines()]
    outcomes = [(line["name"], line["outcome"]) for line in lines]
    print("   audit outcomes:", outcomes)
    results.append(
        ok(
            "audit file: denied + ok lines, no values",
            ("list_records", "denied") in outcomes
            and ("delete_record", "ok") in outcomes
            and "safe to delete" not in open(audit).read(),
        )
    )

    # C. --write-confirm over stdio, both client modes
    for mode in ("legacy", "auto"):
        seen = []

        async def accept(message, response_type, params, context):
            seen.append(message)
            return True

        async def decline(message, response_type, params, context):
            return ElicitResult(action="decline")

        async with Client(
            transport("--write-confirm", "--audit-log", "off"),
            mode=mode,
            elicitation_handler=accept,
        ) as c:
            created = (
                await c.call_tool(
                    "create_record",
                    {
                        "table_name": "incident",
                        "data": {"short_description": "mcp confirm smoke (safe to delete)"},
                    },
                )
            ).data
            sid = created["sys_id"]
            upd = (
                await c.call_tool(
                    "update_record",
                    {"table_name": "incident", "sys_id": sid, "data": {"urgency": "1"}},
                )
            ).data
            results.append(
                ok(
                    f"write-confirm[{mode}]: prompt accepted -> updated",
                    upd["record"].get("urgency") == "1"
                    and any("Update incident/" in m for m in seen),
                    seen[0].splitlines()[0] if seen else "",
                )
            )
        async with Client(
            transport("--write-confirm", "--audit-log", "off"),
            mode=mode,
            elicitation_handler=decline,
        ) as c:
            try:
                await c.call_tool(
                    "update_record",
                    {"table_name": "incident", "sys_id": sid, "data": {"urgency": "3"}},
                )
                results.append(ok(f"write-confirm[{mode}]: decline blocks", False))
            except ToolError as e:
                results.append(
                    ok(f"write-confirm[{mode}]: decline blocks", "Declined by user" in str(e))
                )
        async with Client(transport("--write-confirm", "--audit-log", "off"), mode=mode) as c:
            try:
                await c.call_tool("delete_record", {"table_name": "incident", "sys_id": sid})
                results.append(
                    ok(f"write-confirm[{mode}]: no handler -> confirmation_required", False)
                )
            except ToolError as e:
                results.append(
                    ok(
                        f"write-confirm[{mode}]: no handler -> confirmation_required",
                        "confirmation_required" in str(e),
                    )
                )
            dele = (
                await c.call_tool(
                    "delete_record",
                    {"table_name": "incident", "sys_id": sid, "confirm": True},
                )
            ).data
            results.append(
                ok(f"write-confirm[{mode}]: confirm=true deletes", dele.get("deleted") is True)
            )

    print(f"\n{sum(results)}/{len(results)} passed")
    return all(results)


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(main()) else 1)
