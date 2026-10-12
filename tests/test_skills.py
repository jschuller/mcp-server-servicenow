"""Tests for the five Agent Skills served over MCP as skill:// resources.

FastMCP's SkillsDirectoryProvider (SEP-2640 convention) exposes, per skill,
``skill://<name>/SKILL.md``, a ``skill://<name>/_manifest`` with SHA-256 digests,
and every reference file. These tests pin that surface so a FastMCP upgrade that
realigns the URI shape fails loudly instead of silently changing the contract.
"""

import hashlib
import json
from importlib.resources import files
from pathlib import Path

import pytest
import yaml
from fastmcp import Client

from servicenow_mcp.server import init_services, mcp
from servicenow_mcp.utils.config import (
    AuthConfig,
    AuthType,
    BasicAuthConfig,
    ServerConfig,
)

SKILL_NAMES = {
    "analyzing-access",
    "exploring-tables",
    "reviewing-update-sets",
    "servicenow-cmdb",
    "triaging-incidents",
}
REFERENCE_URIS = {
    "skill://analyzing-access/references/access-errors.md",
    "skill://analyzing-access/references/acl-evaluation.md",
    "skill://exploring-tables/references/query-syntax.md",
    "skill://reviewing-update-sets/references/update-set-fields.md",
    "skill://servicenow-cmdb/references/cmdb-tables.md",
    "skill://servicenow-cmdb/references/csdm5.md",
    "skill://triaging-incidents/references/incident-fields.md",
}
SKILLS_ROOT = Path(str(files("servicenow_mcp").joinpath("skills")))


def _frontmatter(path: Path) -> dict:
    """Parse a SKILL.md frontmatter block the way FastMCP 4.0.4+ does (YAML)."""
    _, block, _ = path.read_text(encoding="utf-8").split("---", 2)
    return yaml.safe_load(block)


@pytest.fixture(autouse=True)
def _init_services() -> None:
    config = ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="admin", password="test123"),
        ),
    )
    init_services(config)

    import servicenow_mcp.resources  # noqa: F401


async def _read_text(client: Client, uri: str) -> str:
    content = await client.read_resource(uri)
    return content[0].text if hasattr(content[0], "text") else str(content[0])


class TestSkillListing:
    async def test_four_skill_md_resources(self) -> None:
        async with Client(mcp) as client:
            uris = {str(r.uri) for r in await client.list_resources()}
        skill_md = {
            u for u in uris if u.startswith("skill://") and u.endswith("/SKILL.md")
        }
        assert {u.split("/")[2] for u in skill_md} == SKILL_NAMES

    async def test_uri_shape_is_sep_2640_convention(self) -> None:
        """Guard: skill://<dir>/SKILL.md — a FastMCP realignment must be reviewed."""
        async with Client(mcp) as client:
            uris = {str(r.uri) for r in await client.list_resources()}
        for name in SKILL_NAMES:
            assert f"skill://{name}/SKILL.md" in uris
            assert f"skill://{name}/_manifest" in uris

    async def test_reference_files_listed_as_markdown(self) -> None:
        async with Client(mcp) as client:
            by_uri = {str(r.uri): r for r in await client.list_resources()}
        listed = {u for u in by_uri if "/references/" in u}
        assert listed == REFERENCE_URIS
        assert all(by_uri[u].mime_type == "text/markdown" for u in listed)

    async def test_counts_static_and_template(self) -> None:
        async with Client(mcp) as client:
            resources = await client.list_resources()
            templates = await client.list_resource_templates()
        assert sum(str(r.uri).startswith("skill://") for r in resources) == 17
        assert len(resources) == 21
        assert len(templates) == 1  # servicenow://schema/{table_name} only

    async def test_read_only_mode_keeps_skills(self) -> None:
        mcp.disable(tags={"write"}, components={"tool"})
        async with Client(mcp) as client:
            resources = await client.list_resources()
        assert sum(str(r.uri).startswith("skill://") for r in resources) == 17


class TestSkillFrontmatter:
    @pytest.mark.parametrize("name", sorted(SKILL_NAMES))
    async def test_description_is_the_frontmatter_description(self, name: str) -> None:
        frontmatter = _frontmatter(SKILLS_ROOT / name / "SKILL.md")
        async with Client(mcp) as client:
            by_uri = {str(r.uri): r for r in await client.list_resources()}
        wire = by_uri[f"skill://{name}/SKILL.md"].description
        assert wire == frontmatter["description"]
        assert frontmatter["name"] == name
        assert '\\"' not in wire, "escaped quotes leak into the wire description"
        assert 0 < len(wire) <= 1024  # agentskills.io limit

    @pytest.mark.parametrize("name", sorted(SKILL_NAMES))
    def test_no_client_specific_allowed_tools(self, name: str) -> None:
        """allowed-tools is experimental in the Agent Skills spec and its old values
        hardcoded plugin-only tool names; the skills must stay client-neutral."""
        frontmatter = _frontmatter(SKILLS_ROOT / name / "SKILL.md")
        assert "allowed-tools" not in frontmatter
        assert (
            "mcp__plugin_servicenow"
            not in (SKILLS_ROOT / name / "SKILL.md").read_text()
        )


class TestSkillContent:
    async def test_skill_md_body(self) -> None:
        async with Client(mcp) as client:
            text = await _read_text(client, "skill://triaging-incidents/SKILL.md")
        assert "# Triaging ServiceNow Incidents" in text

    async def test_reference_read(self) -> None:
        async with Client(mcp) as client:
            text = await _read_text(
                client, "skill://triaging-incidents/references/incident-fields.md"
            )
        assert "Priority Matrix" in text

    @pytest.mark.parametrize("name", sorted(SKILL_NAMES))
    async def test_manifest_digests_match_package_files(self, name: str) -> None:
        async with Client(mcp) as client:
            manifest = json.loads(await _read_text(client, f"skill://{name}/_manifest"))
        assert manifest["skill"] == name
        on_disk = {
            p.relative_to(SKILLS_ROOT / name).as_posix(): "sha256:"
            + hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (SKILLS_ROOT / name).rglob("*")
            if p.is_file()
        }
        assert {f["path"]: f["hash"] for f in manifest["files"]} == on_disk
        assert "SKILL.md" in on_disk

    async def test_path_traversal_rejected(self) -> None:
        async with Client(mcp) as client:
            with pytest.raises(Exception):
                await client.read_resource(
                    "skill://triaging-incidents/../../etc/passwd"
                )

    async def test_unknown_skill_rejected(self) -> None:
        async with Client(mcp) as client:
            with pytest.raises(Exception):
                await client.read_resource("skill://no-such-skill/SKILL.md")


def test_skills_ship_as_package_data() -> None:
    """The wheel includes src/servicenow_mcp/skills/** (hatchling packages=)."""
    for name in SKILL_NAMES:
        assert (SKILLS_ROOT / name / "SKILL.md").is_file()
