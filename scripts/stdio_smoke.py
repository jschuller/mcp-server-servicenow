"""End-to-end smoke over a real stdio subprocess against a live instance.

Complements the pytest suites: exercises the actual server process (CLI flags,
audit file, skills served as resources, both protocol eras) the way a real MCP
client does.

Credentials come only from the environment (SERVICENOW_* variables, as the
server itself reads them), so launch it under a secret-store wrapper, never
with values in a file:

    with-secrets SERVICENOW_API_KEY=svc/homelab/servicenow-<instance>-apikey -- \\
      env SERVICENOW_INSTANCE_URL=https://<instance>.service-now.com \\
          SERVICENOW_AUTH_TYPE=api_key \\
      uv run python scripts/stdio_smoke.py --profile readonly

Profiles:
  readonly  the identity has snc_read_only (the default): without any flag the
            write tools are hidden (13 tools) and a write call is refused
            before it reaches ServiceNow. An identity that cannot read its own
            sys_user_has_role rows sees all 20 (the check fails open) and the
            write comes back as ServiceNow's refusal. Changes nothing.
  write     the identity can create, update and delete incidents and update
            sets (admin by default). Creates and deletes one scratch incident and
            one empty update set; the caller's current update set is restored.

--expect-tools N asserts how many tools the identity lists with no flag, as
docs/testing.md gives it per identity tier, so a fail-open is a FAIL.

Every run also starts the server with --skills off --read-only: 3 resources
and the schema template, no skill://, the same read tools, and instructions
that name no skill. Changes nothing.
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
sys.path.insert(0, REPO)
from tests.inventory import ALL_TOOLS, READ_TOOLS  # noqa: E402  (the one tool list)

DATA_RESOURCES = {
    "servicenow://instance",
    "servicenow://update-set/current",
    "servicenow://cmdb/classes",
}
SCHEMA_TEMPLATE = "servicenow://schema/{table_name}"
SKILLS = (
    "analyzing-access",
    "exploring-tables",
    "reviewing-update-sets",
    "servicenow-cmdb",
)
REFUSED = (
    "401",
    "403",
    "ACL",
    "not authorized",
    "Insufficient",
    "write tools are hidden",
)


def transport(*flags):
    # Each section sets --skills itself when it needs off; the rest test the default.
    env = {k: v for k, v in os.environ.items() if k != "SERVICENOW_SKILLS"}
    return StdioTransport(
        sys.executable,
        ["-m", "servicenow_mcp.cli", *flags],
        env=env,
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
            ok(
                f"read-only: {len(READ_TOOLS)} tools listed",
                {t.name for t in tools} == READ_TOOLS,
                str(len(tools)),
            )
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
                "read-only: 19 resources incl. 15 skill://",
                len(res) == 19
                and sum(str(r.uri).startswith("skill://") for r in res) == 15,
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


async def section_b(results, profile, audit, expect_tools=None):
    """Default mode: identifier and javascript: policy, schema, paging, then writes."""
    async with Client(transport("--audit-log", audit)) as c:
        tools = await c.list_tools()
        roles = (await c.call_tool("get_current_user", {})).structured_content.get(
            "roles"
        )
        if profile == "readonly" and roles is None:
            info("identity cannot read its own role rows: hiding fails open")
        if expect_tools is not None:
            # The count docs/testing.md gives for this identity tier: a
            # fail-open the tier should not see becomes a FAIL, not an INFO.
            want, how = expect_tools, " (--expect-tools)"
        else:
            want = (
                len(READ_TOOLS)
                if profile == "readonly" and roles is not None
                else len(ALL_TOOLS)
            )
            how = ""
        results.append(
            ok(
                f"no flag: {want} tools for this identity{how}",
                len(tools) == want,
                str(len(tools))
                + (", role lookup failed open" if roles is None else ""),
            )
        )
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
        results.append(
            ok("JS policy allows gs.daysAgo()", "records" in r.structured_content)
        )
        existing = (r.structured_content.get("records") or [{}])[0].get("sys_id")
        try:
            schema = (
                await c.call_tool("get_table_schema", {"table_name": "incident"})
            ).structured_content
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
        try:
            rel = await c.call_tool(
                "get_ci_relationships", {"sys_id": "0" * 32, "limit": 5}
            )
            results.append(
                ok(
                    "get_ci_relationships paging arg accepted",
                    rel.structured_content["count"] == 0,
                )
            )
        except ToolError as e:
            # cmdb_rel_ci needs itil or a CMDB read role.
            info("get_ci_relationships refused", str(e).splitlines()[0][:140])
        try:
            agg = await c.call_tool(
                "aggregate_records", {"table_name": "incident", "group_by": "priority"}
            )
            info(
                "aggregate_records", f"ok, {agg.structured_content.get('count')} groups"
            )
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
        ).structured_content
        sid = created["sys_id"]
        results.append(
            ok("create scratch incident", bool(sid), created["record"].get("number"))
        )
        deleted = False
        try:
            upd = (
                await c.call_tool(
                    "update_record",
                    {"table_name": "incident", "sys_id": sid, "data": {"urgency": "2"}},
                )
            ).structured_content
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
            ).structured_content
            deleted = True
            results.append(
                ok(
                    "default: delete_record returns dict",
                    dele == {"deleted": True, "table": "incident", "sys_id": sid},
                )
            )
        finally:
            # A failed step must not leave the scratch incident behind.
            if not deleted:
                try:
                    await c.call_tool(
                        "delete_record", {"table_name": "incident", "sys_id": sid}
                    )
                    info("scratch incident deleted after a failed step", sid)
                except Exception as e:  # cleanup must not mask the first error
                    if "Not found (404)" in str(e):
                        info("scratch incident already deleted", sid)
                    else:
                        info(
                            f"scratch incident {sid} NOT deleted: delete it by hand",
                            str(e).splitlines()[0][:120],
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
    skill_dir = Path(REPO) / "src/servicenow_mcp/skills/analyzing-access"
    for mode in ("legacy", "auto"):
        async with Client(transport("--audit-log", skills_audit), mode=mode) as c:
            uris = {str(r.uri) for r in await c.list_resources()}
            listed = {
                u for u in uris if u.startswith("skill://") and u.endswith("/SKILL.md")
            }
            results.append(
                ok(
                    f"skills[{mode}]: {len(SKILLS)} SKILL.md listed",
                    listed == {f"skill://{n}/SKILL.md" for n in SKILLS},
                )
            )
            body = (await c.read_resource("skill://analyzing-access/SKILL.md"))[0].text
            results.append(
                ok(
                    f"skills[{mode}]: SKILL.md body",
                    "# Analyzing ServiceNow Access" in body,
                )
            )
            manifest = json.loads(
                (await c.read_resource("skill://analyzing-access/_manifest"))[0].text
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
                    "skill://analyzing-access/references/access-errors.md"
                )
            )[0].text
            results.append(
                ok(f"skills[{mode}]: reference read", "## Silent effects" in ref)
            )
            qs = (await c.read_resource("servicenow://help/query-syntax"))[0].text
            results.append(ok(f"skills[{mode}]: query-syntax help", "STARTSWITH" in qs))
            ref = (
                await c.read_resource(
                    "skill://exploring-tables/references/query-syntax.md"
                )
            )[0].text
            results.append(
                ok(f"skills[{mode}]: query-syntax alias = skill reference", ref == qs)
            )
            results.append(
                ok(
                    f"skills[{mode}]: instructions on wire",
                    "skill://analyzing-access/SKILL.md" in (c.instructions or ""),
                )
            )
    lines = [json.loads(line) for line in open(skills_audit) if line.strip()]
    results.append(
        ok(
            "skills: audit resource_read line for skill://",
            any(
                line.get("event") == "resource_read"
                and line.get("name") == "skill://analyzing-access/SKILL.md"
                and line.get("outcome") == "ok"
                for line in lines
            ),
            str(len(lines)),
        )
    )


async def section_f(results: list[bool]) -> None:
    """--skills off: the data resources and the tools stay; no skill is served or named."""
    from servicenow_mcp.server import render_instructions

    async with Client(
        transport("--skills", "off", "--read-only", "--audit-log", "off")
    ) as c:
        uris = {str(r.uri) for r in await c.list_resources()}
        templates = [t.uri_template for t in await c.list_resource_templates()]
        results.append(
            ok(
                "skills off: 3 resources + the schema template, no skill://",
                uris == DATA_RESOURCES and templates == [SCHEMA_TEMPLATE],
                f"{len(uris)} resources, {len(templates)} templates",
            )
        )
        refused_reads = []
        for uri in (
            "skill://analyzing-access/SKILL.md",
            "servicenow://help/query-syntax",
        ):
            try:
                await c.read_resource(uri)
            except Exception:
                refused_reads.append(uri)
        results.append(
            ok(
                "skills off: skill:// and query-syntax not readable",
                len(refused_reads) == 2,
                ", ".join(refused_reads),
            )
        )
        text = c.instructions or ""
        results.append(
            ok(
                "skills off: instructions name no skill",
                text == render_instructions(skills=False)
                and "skill" not in text.lower(),
                f"{len(text)} chars",
            )
        )
        tools = {t.name for t in await c.list_tools()}
        results.append(
            ok(
                f"skills off: {len(READ_TOOLS)} read tools (--read-only)",
                tools == READ_TOOLS,
                str(len(tools)),
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
            results.append(ok("skills off: JS refusal names no query-syntax", False))
        except ToolError as e:
            results.append(
                ok(
                    "skills off: JS refusal names no query-syntax",
                    "unsafe javascript" in str(e)
                    and "servicenow://help/query-syntax" not in str(e),
                )
            )


def pref_rows(data):
    return {r["sys_id"]: r.get("value") for r in data.get("records", [])}


async def section_e(results, profile):
    """Caller identity; in the write profile, the caller-scoped update-set pick."""
    async with Client(transport("--audit-log", "off")) as c:
        me = (await c.call_tool("get_current_user", {})).structured_content
        # Blank under client credentials, where the OAuth application user answers.
        expected = os.environ.get("SERVICENOW_USERNAME") or None
        results.append(
            ok(
                "get_current_user: standard keys",
                {"user_name", "user_sys_id", "user_display_name", "roles"} <= set(me)
                and (expected is None or me["user_name"] == expected),
                me.get("user_name") or "",
            )
        )
        if isinstance(me.get("roles"), list):
            results.append(
                ok(
                    "get_current_user: roles from sys_user_has_role",
                    all(isinstance(r, str) and r for r in me["roles"]),
                    ",".join(me["roles"]),
                )
            )
        else:
            info("get_current_user: this identity cannot read its own role rows")
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
                ).structured_content
            )

        before_mine, before_default = await prefs(mine_q), await prefs(default_q)
        created = (
            await c.call_tool(
                "create_update_set",
                {"name": "mcp smoke (safe to delete)", "description": "stdio smoke"},
            )
        ).structured_content
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
            got = (
                await c.call_tool("get_update_set", {"sys_id": us})
            ).structured_content
            changes = (
                await c.call_tool("list_update_set_changes", {"update_set_sys_id": us})
            ).structured_content
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


async def main(profile, expect_tools=None):
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
        await section_b(results, profile, audit, expect_tools)
        check_audit(results, profile, audit)
        await section_d(results, f"{tmp}/skills-audit.jsonl")
        await section_e(results, profile)
        await section_f(results)
    print(f"\n{sum(results)}/{len(results)} passed")
    return all(results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", choices=("readonly", "write"), default="readonly")
    parser.add_argument(
        "--expect-tools",
        type=int,
        help="tools this identity must list with no flag (docs/testing.md)",
    )
    args = parser.parse_args()
    sys.exit(0 if asyncio.run(main(args.profile, args.expect_tools)) else 1)
