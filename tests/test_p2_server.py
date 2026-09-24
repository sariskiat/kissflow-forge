"""P2 acceptance (Node G): the forge_* MCP tool surface.

Fully offline — NO live credentials, no network:
  1. manifest — every forge_* tool named in the Node G spec exists on `create_server()`'s tool
     surface with a buildable schema.
  2. a stringified nested object/array argument is coerced back to structure by
     `_CoerceJsonStringArgs` rather than rejected at the Pydantic boundary, proven for every
     affected real tool through the real `call_tool` path (a plain function call bypasses
     middleware) — 4 arg shapes from the reported-broken Cowork calls (#1/#2/#8), plus the
     `trigger: None` "derive it" shape `forge_set_events` widened its schema for.

Stage E switch: every call goes through `create_server(lifespan)` and an in-process
`fastmcp.Client`, with `_resources()` building one fresh `AppResources` (every family fake) per
test -- the old plain-function calls `getattr(srv, name)(**kwargs)` are gone with the rest of
`app.infrastructure.mcp.server`'s module-level `mcp`.

Several sections of the pre-Stage-E version of this file are gone, not ported, because Stage D
already covers the same ground per-tool, per-family, or the underlying architecture retired the
premise outright:
  - `test_server_still_exposes_the_original_8_kf_tools`: already not ported before Stage E either
    (its own note said so) -- the exact 61-tool set is `tests/unit/infrastructure/mcp/test_server.
    py::test_registers_only_the_tools_filled_so_far` and `tests/test_tool_surface_snapshot.py`'s job.
  - `test_every_forge_tool_registers_on_the_real_mcp_server_with_a_valid_schema`: the same tool
    surface snapshot test already proves every tool's schema builds and is non-empty.
  - `test_kf_list_field_types_is_a_real_offline_call`, `test_kf_plan_field_change_is_a_real_
    offline_call`, `test_kf_plan_step_visibility_is_a_real_offline_call`,
    `test_kf_list_field_types_round_trips_through_the_real_mcp_protocol`: ported per-tool to
    `tests/unit/application/use_cases/meta/test__field_types.py` (group 9) and `tests/unit/
    application/use_cases/intake/test_kf_plan_field_change.py`/`test_kf_plan_step_visibility.py`
    (group 8), each already driven through the real tool boundary (brief_stage_d_common.md rule
    "argument mapping through fastmcp.Client(create_server(fake_lifespan))").
  - `test_forge_tool_fails_gracefully_with_no_credentials`: its own premise (no `KF_DEV_*` env at
    all) cannot occur once a server is running -- `Settings` is now resolved ONCE at process boot
    (`app.main.main`, spec G2) and handed to every call through the lifespan context, so a missing
    `KF_DEV_DOMAIN`/`KF_DEV_ACCOUNT_ID` now stops the process before `create_server` is ever
    called (`tests/unit/test_main.py::test_missing_kf_dev_domain_stops_boot_and_names_the_key`),
    never surfaces as a per-call graceful failure. The per-call credential gate that DOES still
    exist -- a missing KEY PAIR, `caller_keys(settings)` -- is proven per-family already (every
    `tests/unit/infrastructure/mcp/tools/test_*.py` has its own "no key pair fails before the use
    case runs" parametrized case).
  - The `forge_publish`/`kf_get_flow_schema` page-kind blocks, `test_forge_create_app_happy_path`,
    `test_forge_share_report_happy_path`, and the three create-process/create-flow template-path
    tests: ported (`stage_d_ported.md` groups 4 and 6; the two template-path rows this file's own
    group-4 pass missed are ported by a later flow review fix round).
  - `test_forge_set_branch_conditions_happy_path`/`_rejects_bad_literal_before_any_write` and
    `test_forge_add_goto_gate_branch_name_scopes_into_that_branch`: the same behavior, through the
    same real tool boundary, is proven in `tests/unit/infrastructure/mcp/tools/test_flow.py`
    (group 3), off `test_client.py`'s lower-level `apply_branch_conditions`/`apply_goto_gate`
    ports (`stage_d_ported.md` group 3).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastmcp import Client, FastMCP
from tests.fakes.app import FakeAppRepository
from tests.fakes.artifacts import FakeArtifactWriter
from tests.fakes.copilot import FakeCopilotService
from tests.fakes.dataset import FakeDatasetRepository
from tests.fakes.docs import FakeDocsReader
from tests.fakes.flow import FakeFlowRepository
from tests.fakes.item import FakeItemService
from tests.fakes.page import FakePageRepository

from app.infrastructure.config.settings import Settings
from app.infrastructure.mcp.lifespan import AppResources
from app.infrastructure.mcp.server import create_server

FORGE_TOOLS = {
    "forge_create_process",
    "forge_member_batch",
    "forge_apply_fields",
    "forge_add_table",
    "forge_build_workflow",
    "forge_add_goto_gate",
    "forge_set_branch_conditions",
    "forge_set_visibility",
    "forge_set_events",
    "forge_delete_fields",
    "forge_rename_fields",
    "forge_set_required",
    "forge_set_styles",
    "forge_publish",
    "forge_doctor",
    "forge_create_page",
    "forge_build_page",
    "forge_set_navigation",
    "forge_share_report",
    "forge_simulate_case",
    "forge_create_app",
    "forge_delete_flow",
    "forge_add_role_users",
    "forge_grant_tier",
    "forge_create_flow",
    "forge_publish_app",
    "forge_dataset_records",
    "forge_set_role_preference",
    "forge_sweep",
    "forge_copilot_ask",
    "forge_copilot_check",
    "forge_create_template_app",
}

# Minimal dummy args each forge_* tool needs to reach its FIRST real statement — well-typed
# enough to pass FastMCP's schema / the request DTO's own validation.
DUMMY_ARGS: dict[str, dict[str, Any]] = {
    "forge_create_process": {"name": "x"},
    "forge_member_batch": {"target_flow_id": "x"},
    "forge_apply_fields": {"flow_id": "x", "fields": []},
    "forge_add_table": {"flow_id": "x", "name": "t", "columns": []},
    "forge_build_workflow": {"flow_id": "x", "steps": []},
    "forge_add_goto_gate": {
        "flow_id": "x",
        "target_activity_name": "a",
        "field_name": "f",
    },
    "forge_set_branch_conditions": {
        "flow_id": "x",
        "field_name": "f",
        "branch_literals": {},
    },
    "forge_set_visibility": {"flow_id": "x", "owners": {}},
    "forge_set_events": {"flow_id": "x", "events": {}},
    "forge_delete_fields": {"flow_id": "x", "fields": ["f"]},
    "forge_rename_fields": {"flow_id": "x", "renames": {}},
    "forge_set_required": {"flow_id": "x", "required": []},
    "forge_set_styles": {"flow_id": "x", "styles": {}},
    "forge_publish": {"kind": "process", "flow_id": "x"},
    "forge_doctor": {"flow_id": "x"},
    "forge_create_page": {"app_id": "x", "name": "p"},
    "forge_build_page": {"app_id": "x", "page_id": "p", "steps": []},
    "forge_set_navigation": {"app_id": "x", "page_id": "p", "label": "l"},
    "forge_share_report": {"flow_id": "x", "report_id": "r", "members": []},
    "forge_simulate_case": {"flow_id": "x", "steps": []},
    "forge_create_app": {"name": "x"},
    "forge_delete_flow": {"kind": "process", "flow_id": "x"},
    "forge_add_role_users": {"role_id": "x", "user_query": "ann"},
    "forge_grant_tier": {
        "kind": "process",
        "flow_id": "x",
        "role_id": "r",
        "tier": "Manage",
    },
    "forge_create_flow": {"kind": "process", "name": "x"},
    "forge_publish_app": {"app_id": "x"},
    "forge_dataset_records": {"flow_id": "x", "op": "list"},
    "forge_set_role_preference": {"role_id": "x", "default_page": "Default"},
    "forge_sweep": {"scope": "apps"},
    "forge_copilot_ask": {"app_id": "x", "message": "hi"},
    "forge_copilot_check": {"app_id": "x", "conversation_id": "c1"},
    "forge_create_template_app": {"name": "x"},
}


def _settings() -> Settings:
    return Settings(
        kf_dev_domain="dev-acme.kissflow.com",
        kf_dev_account_id="A1",
        kf_app="App1",
        kf_process_template=None,
        port=8080,
        mcp_http=False,
        kf_dev_access_key_id="k1",
        kf_dev_access_key_secret="s1",
        http_timeout_seconds=10.0,
    )


def _resources() -> AppResources:
    return AppResources(
        flow=FakeFlowRepository(),
        app=FakeAppRepository(),
        artifacts=FakeArtifactWriter(),
        page=FakePageRepository(),
        dataset=FakeDatasetRepository(),
        item=FakeItemService(),
        copilot=FakeCopilotService(),
        docs=FakeDocsReader(),
    )


def _server() -> FastMCP:
    resources = _resources()

    @asynccontextmanager
    async def _lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
        del server
        yield {"resources": resources, "settings": _settings()}

    return create_server(_lifespan)


def _listed_names() -> set[str]:
    async def _run() -> set[str]:
        async with Client(_server()) as client:
            return {t.name for t in await client.list_tools()}

    return asyncio.run(_run())


def test_dummy_args_cover_every_forge_tool() -> None:
    """Fixture-drift guard: if a new forge_* tool is added, this file must know how to probe it."""
    assert set(DUMMY_ARGS) == FORGE_TOOLS


# ---- 1. manifest ------------------------------------------------------------------------------


def test_server_exposes_every_forge_tool_by_name() -> None:
    found = _listed_names()
    missing = FORGE_TOOLS - found
    assert not missing, (
        f"forge_* tools missing from the server's tool surface: {missing}"
    )


# ---- 2. a stringified nested object/array argument is coerced, not rejected -------------------


@pytest.mark.parametrize(
    "tool_name, args",
    [
        # every nested object/array param a client (Cowork) was seen to stringify — all 4 reported-broken
        # calls (#1/#2/#8), not just `sections`. The VALUE is a JSON STRING, as Cowork sends it.
        (
            "forge_apply_fields",
            {
                "flow_id": "F1",
                "fields": [],
                "sections": json.dumps({"Case Info": ["A", "B"]}),
            },
        ),
        (
            "forge_create_flow",
            {
                "kind": "case",
                "name": "N",
                "extra": json.dumps({"item_type": "Board", "prefix": "CS"}),
            },
        ),
        (
            "forge_build_page",
            {
                "app_id": "A",
                "page_id": "P",
                "steps": json.dumps([{"kind": "container", "kwargs": {}}]),
            },
        ),
        ("forge_build_page", {"app_id": "A", "op": json.dumps({"name": "P"})}),
        # forge_set_events' `trigger: None` "derive it" shape, plus the same arg JSON-stringified —
        # a schema that rejected `null` at the Pydantic boundary would never reach the derivation.
        (
            "forge_set_events",
            {"flow_id": "F1", "events": {"Route": [[None, "kf.x();"]]}},
        ),
        (
            "forge_set_events",
            {"flow_id": "F1", "events": json.dumps({"Route": [[None, "kf.x();"]]})},
        ),
    ],
)
def test_stringified_structured_arg_is_coerced_not_rejected(
    tool_name: str, args: dict[str, Any]
) -> None:
    """The `_CoerceJsonStringArgs` middleware must `json.loads` a stringified object/array arg
    back so Pydantic doesn't reject it with `dict_type`/`list_type` before our own code runs.
    Proven for EVERY affected tool through the real `call_tool` path (a plain function call
    bypasses middleware) -- coercion success means the call reaches the use case at all (a fake
    port then answers it, successfully or not, but never with a schema-validation error).
    """

    async def _run() -> str:
        async with Client(_server()) as client:
            result = await client.call_tool(tool_name, args, raise_on_error=False)
        return str(result.content)

    txt = asyncio.run(_run())
    assert "dict_type" not in txt and "list_type" not in txt, txt
