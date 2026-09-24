"""`create_server(lifespan)`: the new, thin server (spec G12 skeleton, built
in Stage C).

Every family's tool modules start with zero real `@mcp.tool` functions
(their work groups are empty, filled in Stage D), so the "subset surface"
test below passes vacuously until a group lands -- as each family writer
adds a real tool, this same test starts checking it against
`tests/fixtures/tool_surface.json`, with no change to this file.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client, FastMCP

from app.infrastructure.mcp.server import _CoerceJsonStringArgs, create_server

FIXTURE_PATH = Path(__file__).resolve().parents[3] / "fixtures" / "tool_surface.json"


@asynccontextmanager
async def _fake_lifespan(server: FastMCP) -> Any:
    del server
    yield {"resources": None, "settings": None}


def _server() -> FastMCP:
    return create_server(_fake_lifespan)


async def _list_tools(server: FastMCP) -> list[Any]:
    async with Client(server) as client:
        return await client.list_tools()


def test_mask_error_details_is_true() -> None:
    """No raw exception detail ever reaches a client (spec G6)."""
    assert _server()._mask_error_details is True


def test_registers_the_coerce_json_string_args_middleware() -> None:
    """The same client-compat middleware the old server uses (spec G12)."""
    server = _server()
    assert any(isinstance(m, _CoerceJsonStringArgs) for m in server.middleware)


@pytest.mark.asyncio
async def test_the_lifespan_it_was_built_with_actually_runs() -> None:
    """The lifespan this server was built with is the one FastMCP calls -- connecting
    alone drives `_fake_lifespan`'s context manager open and closed with no error."""
    async with Client(_server()):
        pass


@pytest.mark.asyncio
async def test_registers_only_the_tools_filled_so_far() -> None:
    """Today's state, pinned: every Stage D group has landed here (group 1,
    flow fields; group 2, flow structure; group 3, flow workflow; group 4,
    flow lifecycle; group 5, app roles; group 6, app family apps; group 7,
    page dataset item copilot; group 8, design and intake; group 9, meta) --
    all 61 tools, with no group left empty. This test now pins the full,
    final tool surface, with no change to the fixture check below, which is
    what actually proves HR3 for every tool that lands."""
    names = {t.name for t in await _list_tools(_server())}
    assert names == {
        # group 1, flow fields
        "kf_apply_field_change",
        "forge_apply_fields",
        "forge_apply_layout",
        "forge_delete_fields",
        "forge_rename_fields",
        "forge_set_required",
        # group 2, flow structure
        "forge_add_table",
        "forge_add_sequence_number",
        "forge_add_field_validation",
        "forge_set_styles",
        "forge_set_events",
        # group 3, flow workflow
        "forge_add_goto_gate",
        "forge_build_workflow",
        "forge_set_branch_conditions",
        "forge_set_visibility",
        "kf_set_step_visibility",
        # group 4, flow lifecycle
        "kf_create_process",
        "forge_create_process",
        "forge_create_flow",
        "forge_create_list",
        "forge_delete_flow",
        "forge_publish",
        "kf_publish",
        "kf_get_flow_schema",
        "forge_doctor",
        # group 5, app roles
        "forge_member_batch",
        "forge_add_member_roles",
        "forge_create_app_role",
        "forge_delete_app_role",
        "forge_list_app_roles",
        "forge_add_role_users",
        "forge_grant_tier",
        "forge_set_role_preference",
        # group 6, app apps
        "forge_create_app",
        "forge_list_apps",
        "forge_publish_app",
        "forge_create_template_app",
        "forge_share_report",
        "forge_sweep",
        # group 9, meta
        "forge_playbook",
        "forge_capabilities",
        "kf_list_field_types",
        # group 7, page dataset item copilot
        "forge_create_page",
        "forge_build_page",
        "forge_set_navigation",
        "forge_dataset_records",
        "forge_simulate_case",
        "forge_copilot_ask",
        "forge_copilot_check",
        # group 8, design family
        "forge_render_flow_diagram",
        "forge_render_schema_diagram",
        "forge_render_mockups",
        # group 8, intake family
        "kf_plan_field_change",
        "kf_plan_step_visibility",
        "forge_intake_questions",
        "forge_update_spec",
        "forge_request_confirmation",
        "forge_apply_revisions",
        "forge_approve_spec",
        "forge_plan_app",
        "forge_compare_to_spec",
    }


@pytest.mark.asyncio
async def test_every_registered_tool_matches_the_frozen_surface() -> None:
    """Every tool `create_server()` actually registers -- today, none -- has the same
    input schema and docstring hash as the frozen surface fixture. As Stage D adds real
    tools, this test starts checking them with no change to this file."""
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    tools = await _list_tools(_server())

    for tool in tools:
        assert tool.name in fixture["tools"], (
            f"{tool.name} is not in the frozen surface"
        )
        expected = fixture["tools"][tool.name]
        assert tool.input_schema == expected["parameters"]
        description = tool.description or ""
        digest = hashlib.sha256(description.encode("utf-8")).hexdigest()
        assert digest == expected["docstring_sha256"]
