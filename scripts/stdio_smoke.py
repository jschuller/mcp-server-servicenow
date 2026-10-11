"""End-to-end smoke over a real stdio subprocess against a live instance.

Complements the pytest suites: exercises the actual server process (CLI flags,
audit file, skills served as resources, both protocol eras) the way a real MCP
client does.

Credentials come only from the environment (SERVICENOW_* variables, as the
server itself reads them), so launch it under a secret-store wrapper, never
with values in a file:

    with-secrets SERVICENOW_API_KEY=svc/homelab/servicenow-<instance>-apikey -- \\
      env SERVICENOW_INSTANCE_URL=https://<instance>.service-now.com \\
          SERVICENOW_AUTH_TYPE=api_key SERVICENOW_API_KEY_HEADER=x-sn-apikey \\
      uv run python scripts/stdio_smoke.py --profile readonly

Profiles:
  readonly  the identity cannot write (the default). A write tool is called
            anyway and must come back as a clean ServiceNow refusal. Changes
            nothing.
  write     the identity can create, update and delete incidents and update
            sets (admin by default). Creates and deletes scratch incidents and
            one empty update set; the caller's current update set is restored.
"""

import argparse
import asyncio
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from fastmcp.exceptions import ToolError

REPO = str(Path(__file__).resolve().parents[1])
SKILLS = (
    "exploring-tables",
    "reviewing-update-sets",
    "servicenow-cmdb",
    "triaging-incidents",
)
REFUSED = ("401", "403", "ACL", "not authorized", "Insufficient")


def transport(*flags):
    return StdioTransport(
        sys.executable,
        ["-m", "servicenow_mcp.cli", *flags],
        env=dict(os.environ),
        cwd=REPO,
    )


def ok(label, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + label + (f"  [{extra}]" if extra else ""))
    return cond


def info(label, extra=""):
    print("INFO " + label + (f"  [{extra}]" if extra else ""))


def refused(exc):
    return any(marker in str(exc) for marker in REFUSED)


async def section_a(results):
    """--read-only hides the write tools; annotations and resources on the wire."""
    async with Client(transport("--read-only", "--audit-log", "off")) as c:
        tools = await c.list_tools()
        results.append(
            ok("read-only: 12 tools listed", len(tools) == 12, str(len(tools)))
        )
        ann = {t.name: t.annotations for t in tools}
        results.append(
            ok(
                "annotations on wire",
                ann["list_records"] is not None
                and ann["list_records"].read_only_hint is True,
            )
        )
        res = await c.list_resources()
        results.append(
            ok(
                "read-only: 15 resources incl. 11 skill://",
                len(res) == 15
                and sum(str(r.uri).startswith("skill://") for r in res) == 11,
                str(len(res)),
            )
        )
        try:
            await c.call_tool(
                "delete_record", {"table_name": "incident", "sys_id": "x"}
            )
            results.append(ok("read-only: delete_record hidden", False))
        except ToolError as e:
            results.append(
                ok("read-only: delete_record -> Unknown tool", "Unknown tool" in str(e))
            )


async def section_b(results, profile, audit):
    """Default mode: identifier and javascript: policy, schema, paging, then writes."""
    async with Client(transport("--audit-log", audit)) as c:
        tools = await c.list_tools()
        results.append(ok("default: 19 tools", len(tools) == 19, str(len(tools))))
        try:
            await c.call_tool(
                "list_records", {"table_name": "incident^ORx", "limit": 1}
            )
            results.append(ok("policy rejects an invalid table name", False))
        except ToolError as e:
            results.append(
                ok(
                    "policy rejects an invalid table name",
                    "Invalid table name" in str(e),
                )
            )
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
                "fields": "sys_id,number,urgency",
                "limit": 1,
            },
        )
        results.append(ok("JS policy allows gs.daysAgo()", "records" in r.data))
        existing = (r.data.get("records") or [{}])[0].get("sys_id")
        try:
            schema = (
                await c.call_tool("get_table_schema", {"table_name": "incident"})
            ).data
            by_name = {f["name"]: f for f in schema["fields"]}
            results.append(
                ok(
                    "schema: incident inherits task.number",
                    by_name.get("number", {}).get("defined_in") == "task",
                    f"hierarchy={schema['hierarchy']} fields={schema['field_count']}",
                )
            )
        except ToolError as e:
            # Without personalize_dictionary the instance refuses sys_dictionary.
            results.append(
                ok(
                    "schema: refused with the role hint (identity lacks personalize_dictionary)",
                    "personalize_dictionary" in str(e),
                )
            )
        rel = await c.call_tool(
            "get_ci_relationships", {"sys_id": "0" * 32, "limit": 5}
        )
        results.append(
            ok("get_ci_relationships paging arg accepted", rel.data["count"] == 0)
        )
        try:
            agg = await c.call_tool(
                "aggregate_records", {"table_name": "incident", "group_by": "priority"}
            )
            info("aggregate_records", f"ok, {agg.data.get('count')} groups")
        except ToolError as e:
            # API keys need a REST API access policy for the Aggregate API too.
            info("aggregate_records refused", str(e).splitlines()[0][:140])

        if profile == "readonly":
            try:
                await c.call_tool(
                    "update_record",
                    {
                        "table_name": "incident",
                        "sys_id": existing or "0" * 32,
                        "data": {"urgency": "3"},
                    },
                )
                results.append(ok("read-only identity: write refused cleanly", False))
            except ToolError as e:
                results.append(
                    ok(
                        "read-only identity: write refused cleanly",
                        refused(e),
                        str(e).splitlines()[0][:120],
                    )
                )
            return

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
        results.append(
            ok("create scratch incident", bool(sid), created["record"].get("number"))
        )
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
            await c.call_tool(
                "delete_record", {"table_name": "incident", "sys_id": sid}
            )
        ).data
        results.append(
            ok(
                "default: delete_record returns dict",
                dele == {"deleted": True, "table": "incident", "sys_id": sid},
            )
        )
        return


def check_audit(results, profile, audit):
    text = Path(audit).read_text()
    outcomes = [
        (line["name"], line["outcome"]) for line in map(json.loads, text.splitlines())
    ]
    print("   audit outcomes:", outcomes)
    wanted_ok = (
        ("list_records", "ok") if profile == "readonly" else ("delete_record", "ok")
    )
    results.append(
        ok(
            "audit file: denied + ok lines, no values",
            ("list_records", "denied") in outcomes
            and wanted_ok in outcomes
            and "safe to delete" not in text,
        )
    )


async def section_d(results, skills_audit):
    """Skills over MCP (SEP-2640 shape) and the help resource, both eras."""
    skill_dir = Path(REPO) / "src/servicenow_mcp/skills/triaging-incidents"
    for mode in ("legacy", "auto"):
        async with Client(transport("--audit-log", skills_audit), mode=mode) as c:
            uris = {str(r.uri) for r in await c.list_resources()}
            listed = {
                u for u in uris if u.startswith("skill://") and u.endswith("/SKILL.md")
            }
            results.append(
                ok(
                    f"skills[{mode}]: 4 SKILL.md listed",
                    listed == {f"skill://{n}/SKILL.md" for n in SKILLS},
                )
            )
            body = (await c.read_resource("skill://triaging-incidents/SKILL.md"))[
                0
            ].text
            results.append(
                ok(
                    f"skills[{mode}]: SKILL.md body",
                    "# Triaging ServiceNow Incidents" in body,
                )
            )
            manifest = json.loads(
                (await c.read_resource("skill://triaging-incidents/_manifest"))[0].text
            )
            want = (
                "sha256:"
                + hashlib.sha256((skill_dir / "SKILL.md").read_bytes()).hexdigest()
            )
            results.append(
                ok(
                    f"skills[{mode}]: manifest sha256 matches package file",
                    {f["path"]: f["hash"] for f in manifest["files"]}.get("SKILL.md")
                    == want,
                )
            )
            ref = (
                await c.read_resource(
                    "skill://triaging-incidents/references/incident-fields.md"
                )
            )[0].text
            results.append(
                ok(f"skills[{mode}]: reference read", "Priority Matrix" in ref)
            )
            qs = (await c.read_resource("servicenow://help/query-syntax"))[0].text
            results.append(ok(f"skills[{mode}]: query-syntax help", "STARTSWITH" in qs))
            results.append(
                ok(
                    f"skills[{mode}]: instructions on wire",
                    "skill://triaging-incidents/SKILL.md" in (c.instructions or ""),
                )
            )
    lines = [json.loads(line) for line in open(skills_audit) if line.strip()]
    results.append(
        ok(
            "skills: audit resource_read line for skill://",
            any(
                line.get("event") == "resource_read"
                and line.get("name") == "skill://triaging-incidents/SKILL.md"
                and line.get("outcome") == "ok"
                for line in lines
            ),
            str(len(lines)),
        )
    )


def pref_rows(data):
    return {r["sys_id"]: r.get("value") for r in data.get("records", [])}


async def section_e(results, profile):
    """Caller identity; in the write profile, the caller-scoped update-set pick."""
    async with Client(transport("--audit-log", "off")) as c:
        me = (await c.call_tool("get_current_user", {})).data
        expected = os.environ.get("SERVICENOW_USERNAME")
        results.append(
            ok(
                "get_current_user: standard keys",
                {"user_name", "user_sys_id", "user_display_name", "roles"} <= set(me)
                and (expected is None or me["user_name"] == expected),
                me.get("user_name") or "",
            )
        )
        if profile == "readonly":
            return
        uid = me["user_sys_id"]
        mine_q = f"name=sys_update_set^user={uid}"
        default_q = "name=sys_update_set^userISEMPTY"

        async def prefs(query):
            return pref_rows(
                (
                    await c.call_tool(
                        "list_records",
                        {
                            "table_name": "sys_user_preference",
                            "query": query,
                            "fields": "sys_id,value",
                            "limit": 50,
                        },
                    )
                ).data
            )

        before_mine, before_default = await prefs(mine_q), await prefs(default_q)
        created = (
            await c.call_tool(
                "create_update_set",
                {"name": "mcp smoke (safe to delete)", "description": "stdio smoke"},
            )
        ).data
        us = created["sys_id"]
        results.append(ok("create_update_set", bool(us)))
        try:
            await c.call_tool("set_current_update_set", {"sys_id": us})
            after_mine, after_default = await prefs(mine_q), await prefs(default_q)
            results.append(
                ok(
                    "set_current_update_set: caller's own row only",
                    list(after_mine.values()) == [us]
                    and after_default == before_default,
                    f"mine={len(after_mine)} defaults={len(after_default)}",
                )
            )
            cur = json.loads(
                (await c.read_resource("servicenow://update-set/current"))[0].text
            )
            results.append(
                ok("update-set/current resource follows", cur.get("sys_id") == us)
            )
            got = (await c.call_tool("get_update_set", {"sys_id": us})).data
            changes = (
                await c.call_tool("list_update_set_changes", {"update_set_sys_id": us})
            ).data
            results.append(
                ok(
                    "get_update_set + list_update_set_changes",
                    got.get("name") == "mcp smoke (safe to delete)"
                    and changes.get("count") == 0,
                )
            )
        finally:
            # Put the caller's preference back the way it was, then drop the set.
            row = next(iter((await prefs(mine_q))), None)
            if before_mine:
                sid, value = next(iter(before_mine.items()))
                await c.call_tool(
                    "update_record",
                    {
                        "table_name": "sys_user_preference",
                        "sys_id": sid,
                        "data": {"value": value},
                    },
                )
            elif row:
                await c.call_tool(
                    "delete_record",
                    {"table_name": "sys_user_preference", "sys_id": row},
                )
            await c.call_tool(
                "delete_record", {"table_name": "sys_update_set", "sys_id": us}
            )
        results.append(
            ok(
                "update-set preference restored, scratch set deleted",
                await prefs(mine_q) == before_mine
                and await prefs(default_q) == before_default,
            )
        )


async def main(profile):
    if not os.environ.get("SERVICENOW_INSTANCE_URL"):
        sys.exit("SERVICENOW_INSTANCE_URL is not set (see the module docstring)")
    print(
        f"profile={profile} instance={os.environ['SERVICENOW_INSTANCE_URL']} "
        f"auth={os.environ.get('SERVICENOW_AUTH_TYPE', 'basic')}"
    )
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        audit = f"{tmp}/audit.jsonl"
        await section_a(results)
        await section_b(results, profile, audit)
        check_audit(results, profile, audit)
        await section_d(results, f"{tmp}/skills-audit.jsonl")
        await section_e(results, profile)
    print(f"\n{sum(results)}/{len(results)} passed")
    return all(results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", choices=("readonly", "write"), default="readonly")
    args = parser.parse_args()
    sys.exit(0 if asyncio.run(main(args.profile)) else 1)
