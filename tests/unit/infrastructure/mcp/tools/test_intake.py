"""The intake-family tool module: `register` calls its one work group (Stage D
group 8), which fills every intake tool. Every tool but `forge_compare_to_spec`
is offline (no Kissflow credentials, no network) -- driven through an
in-process `fastmcp.Client`, proving argument mapping and `ApplicationError`
-> `ToolError` through the thin tool, not just through `_shared.run_use_case`
in isolation. Rule 23: an offline tool that calls no Kissflow API skips the
missing-key-pair case.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from tests.fakes.app import FakeAppRepository
from tests.fakes.artifacts import FakeArtifactWriter
from tests.fakes.copilot import FakeCopilotService
from tests.fakes.dataset import FakeDatasetRepository
from tests.fakes.docs import FakeDocsReader
from tests.fakes.flow import FakeFlowRepository
from tests.fakes.item import FakeItemService
from tests.fakes.page import FakePageRepository

from app.application.models.requests.intake.app_spec import AppSpec
from app.domain.entities.flow_draft import FlowDraft
from app.infrastructure.config.settings import Settings
from app.infrastructure.mcp.lifespan import AppResources
from app.infrastructure.mcp.tools import intake as intake_tools

_FIXTURES_DIR = Path(__file__).resolve().parents[4] / "fixtures"
_GOLDEN_DIR = _FIXTURES_DIR / "app_spec_golden"


def _form_draft() -> dict[str, Any]:
    return json.loads((_FIXTURES_DIR / "form_draft.json").read_text())


_TOOL_NAMES = {
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


def _golden(name: str) -> dict[str, Any]:
    return json.loads((_GOLDEN_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _full_wire() -> dict[str, Any]:
    spec = AppSpec.model_validate(_golden("full")).model_copy(
        update={"approved": False}
    )
    return spec.model_dump(mode="json")


async def _tool_names(mcp: FastMCP) -> list[str]:
    async with Client(mcp) as client:
        return [t.name for t in await client.list_tools()]


@pytest.mark.asyncio
async def test_register_runs_the_work_group_without_error() -> None:
    mcp = FastMCP("test")
    intake_tools.register(mcp)
    assert set(await _tool_names(mcp)) == _TOOL_NAMES


@pytest.mark.asyncio
async def test_the_work_group_is_independently_callable() -> None:
    mcp = FastMCP("test")
    intake_tools._register_all(mcp)
    assert set(await _tool_names(mcp)) == _TOOL_NAMES


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "kf_dev_domain": "dev-acme.kissflow.com",
        "kf_dev_account_id": "A1",
        "kf_app": None,
        "kf_process_template": None,
        "port": 8080,
        "mcp_http": False,
        "kf_dev_access_key_id": None,
        "kf_dev_access_key_secret": None,
        "http_timeout_seconds": 10.0,
    }
    base.update(overrides)
    return Settings(**base)


def _lifespan(settings: Settings, flow: FakeFlowRepository | None = None) -> Any:
    @asynccontextmanager
    async def _run(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
        del server
        resources = AppResources(
            flow=flow if flow is not None else FakeFlowRepository(),
            app=FakeAppRepository(),
            page=FakePageRepository(),
            dataset=FakeDatasetRepository(),
            item=FakeItemService(),
            copilot=FakeCopilotService(),
            docs=FakeDocsReader(),
            artifacts=FakeArtifactWriter(),
            approval_secret=b"a" * 32,
        )
        yield {"resources": resources, "settings": settings}

    return _run


def _server(settings: Settings, flow: FakeFlowRepository | None = None) -> FastMCP:
    mcp = FastMCP("test", lifespan=_lifespan(settings, flow))
    intake_tools._register_all(mcp)
    return mcp


# ---- offline, pure tools ------------------------------------------------------------


@pytest.mark.asyncio
async def test_kf_plan_field_change_maps_arguments_and_returns_the_response() -> None:
    draft = _form_draft()
    async with Client(_server(_settings())) as client:
        result = await client.call_tool(
            "kf_plan_field_change",
            {"draft": draft, "changes": [{"name": "Notes", "type": "Text"}]},
        )
    assert result.structured_content["adds"] == [
        {"name": "Notes", "type": "Text", "required": False}
    ]
    assert set(result.structured_content) == {
        "adds",
        "edits",
        "skipped",
        "human_readable",
    }


@pytest.mark.asyncio
async def test_kf_plan_field_change_runs_with_no_key_pair_at_all() -> None:
    settings = _settings(kf_dev_access_key_id=None, kf_dev_access_key_secret=None)
    draft = _form_draft()
    async with Client(_server(settings)) as client:
        result = await client.call_tool(
            "kf_plan_field_change", {"draft": draft, "changes": []}
        )
    assert result.structured_content["adds"] == []


@pytest.mark.asyncio
async def test_kf_plan_field_change_a_bad_type_raises_a_tool_error_with_the_text() -> (
    None
):
    """The `_field_rules.type_is_known` refusal text (fix 1): the DTO's own
    `ValidationError` surfaces through `ToolError` with the old
    `app.application.tools._field_type` message intact."""
    async with Client(_server(_settings())) as client:
        with pytest.raises(ToolError) as exc_info:
            await client.call_tool(
                "kf_plan_field_change",
                {"draft": _form_draft(), "changes": [{"name": "x", "type": "Nope"}]},
            )
    message = str(exc_info.value)
    assert "is not a field type this engine can build" in message
    assert "kf_list_field_types" in message
    assert "forge_capabilities" in message
    assert "ADR-0004" in message


@pytest.mark.asyncio
async def test_kf_plan_field_change_an_application_error_raises_a_tool_error() -> None:
    async with Client(_server(_settings())) as client:
        with pytest.raises(ToolError, match="Root"):
            await client.call_tool(
                "kf_plan_field_change",
                {"draft": {"Root": "Missing"}, "changes": []},
            )


@pytest.mark.asyncio
async def test_kf_plan_step_visibility_an_application_error_raises_a_tool_error() -> (
    None
):
    async with Client(_server(_settings())) as client:
        with pytest.raises(ToolError, match="ProcessDef"):
            await client.call_tool(
                "kf_plan_step_visibility",
                {"draft": {}, "owners": {"Intake": ["Start"]}},
            )


@pytest.mark.asyncio
async def test_kf_plan_step_visibility_maps_arguments_and_returns_the_response() -> (
    None
):
    from synthetic import OWNERS, synthetic_process_draft

    async with Client(_server(_settings())) as client:
        result = await client.call_tool(
            "kf_plan_step_visibility",
            {"draft": synthetic_process_draft(), "owners": OWNERS},
        )
    assert "permission_nodes" in result.structured_content
    assert set(result.structured_content) == {"sections", "permission_nodes"}


@pytest.mark.asyncio
async def test_forge_intake_questions_maps_arguments_and_returns_the_response() -> None:
    async with Client(_server(_settings())) as client:
        result = await client.call_tool("forge_intake_questions", {"limit": 2})
    assert len(result.structured_content["questions"]) == 2
    assert result.structured_content["spec"]["approved"] is False
    assert set(result.structured_content) == {
        "questions",
        "gaps",
        "blocking_gaps",
        "spec",
    }


@pytest.mark.asyncio
async def test_forge_update_spec_maps_arguments_and_returns_the_response() -> None:
    async with Client(_server(_settings())) as client:
        result = await client.call_tool(
            "forge_update_spec", {"spec": None, "patch": {}}
        )
    assert result.structured_content["spec"]["approved"] is False
    assert set(result.structured_content) == {"spec", "gaps", "blocking_gaps"}


@pytest.mark.asyncio
async def test_forge_update_spec_a_refusal_raises_a_tool_error_with_the_message() -> (
    None
):
    async with Client(_server(_settings())) as client:
        with pytest.raises(ToolError, match="confirmation gate"):
            await client.call_tool(
                "forge_update_spec",
                {"spec": _full_wire(), "patch": {"approved": True}},
            )


@pytest.mark.asyncio
async def test_forge_request_confirmation_maps_arguments_and_returns_the_response(
    tmp_path: Path,
) -> None:
    async with Client(_server(_settings())) as client:
        result = await client.call_tool(
            "forge_request_confirmation",
            {"spec": _full_wire(), "out_dir": str(tmp_path)},
        )
    assert len(result.structured_content["digest"]) == 64
    assert result.structured_content["gaps"] == []
    assert set(result.structured_content) == {
        "digest",
        "artifact_paths",
        "questions",
        "gaps",
        "blocking_gaps",
    }


@pytest.mark.asyncio
async def test_forge_apply_revisions_maps_arguments_and_returns_the_response() -> None:
    async with Client(_server(_settings())) as client:
        result = await client.call_tool(
            "forge_apply_revisions",
            {"spec": _full_wire(), "revisions": {"app_name": "Renamed"}},
        )
    assert result.structured_content["spec"]["app_name"] == "Renamed"
    assert result.structured_content["compiles"] is True
    assert set(result.structured_content) == {
        "spec",
        "digest",
        "compiles",
        "compile_error",
    }


@pytest.mark.asyncio
async def test_forge_approve_spec_maps_arguments_and_returns_the_response() -> None:
    async with Client(_server(_settings())) as client:
        confirm = await client.call_tool(
            "forge_request_confirmation", {"spec": _full_wire()}
        )
        result = await client.call_tool(
            "forge_approve_spec",
            {
                "spec": _full_wire(),
                "digest": confirm.structured_content["digest"],
                "decision": "approve",
            },
        )
    assert result.structured_content["approved"] is True
    assert len(result.structured_content["approval_token"]) == 64
    assert set(result.structured_content) == {
        "spec",
        "approved",
        "digest",
        "approval_token",
    }


@pytest.mark.asyncio
async def test_forge_approve_spec_a_non_approve_decision_fails_before_the_tool_runs() -> (  # noqa: E501
    None
):
    """`decision` is the closed literal `Literal["approve"]`: any other value
    fails FastMCP's own argument-schema validation before the tool body (and
    so the use case) ever runs -- this is NOT the `ApplicationError` ->
    `ToolError` path; see `test_forge_approve_spec_a_stale_digest_raises_a_
    tool_error_with_the_message` below for that."""
    async with Client(_server(_settings())) as client:
        with pytest.raises(ToolError):
            await client.call_tool(
                "forge_approve_spec",
                {"spec": _full_wire(), "digest": "x", "decision": "revise"},
            )


@pytest.mark.asyncio
async def test_forge_approve_spec_a_stale_digest_raises_a_tool_error_with_the_message() -> (  # noqa: E501
    None
):
    """The `ApplicationError` -> `ToolError` path (fix 5): a digest that no
    longer matches the spec's current content is refused with the exact
    stale-digest message `ForgeApproveSpec.execute` raises, naming both
    digests."""
    async with Client(_server(_settings())) as client:
        with pytest.raises(ToolError, match="stale digest") as exc_info:
            await client.call_tool(
                "forge_approve_spec",
                {
                    "spec": _full_wire(),
                    "digest": "0" * 64,
                    "decision": "approve",
                },
            )
    assert "0" * 64 in str(exc_info.value)


@pytest.mark.asyncio
async def test_forge_plan_app_maps_arguments_and_returns_the_response() -> None:
    async with Client(_server(_settings())) as client:
        confirm = await client.call_tool(
            "forge_request_confirmation", {"spec": _full_wire()}
        )
        approval = await client.call_tool(
            "forge_approve_spec",
            {
                "spec": _full_wire(),
                "digest": confirm.structured_content["digest"],
                "decision": "approve",
            },
        )
        result = await client.call_tool(
            "forge_plan_app",
            {
                "spec": approval.structured_content["spec"],
                "approval_token": approval.structured_content["approval_token"],
            },
        )
    assert result.structured_content["op_count"] == len(
        result.structured_content["ops"]
    )
    assert set(result.structured_content) == {"ops", "summary", "op_count"}


@pytest.mark.asyncio
async def test_forge_plan_app_an_invalid_token_raises_a_tool_error() -> None:
    async with Client(_server(_settings())) as client:
        with pytest.raises(ToolError, match="approval_token"):
            await client.call_tool(
                "forge_plan_app",
                {"spec": _full_wire(), "approval_token": "0" * 64},
            )


@pytest.mark.asyncio
async def test_a_malformed_spec_raises_a_tool_error() -> None:
    async with Client(_server(_settings())) as client:
        with pytest.raises(ToolError):
            await client.call_tool(
                "forge_apply_revisions",
                {"spec": {"not": "a spec"}, "revisions": {}},
            )


# ---- forge_compare_to_spec: the one LIVE tool in this family -------------------------


@pytest.mark.asyncio
async def test_forge_compare_to_spec_an_empty_app_id_raises_a_tool_error() -> None:
    """The `ApplicationError` -> `ToolError` path (fix 5): no `app_id` given
    and no `KF_APP` default set, so `require_app_id` refuses before any read."""
    flow = FakeFlowRepository()
    settings = _settings(kf_dev_access_key_id="key-1", kf_dev_access_key_secret="s")
    async with Client(_server(settings, flow)) as client:
        with pytest.raises(ToolError, match="no app selected"):
            await client.call_tool(
                "forge_compare_to_spec",
                {"flow_id": "F1", "spec": _full_wire(), "app_id": ""},
            )
    assert flow.calls == []


@pytest.mark.asyncio
async def test_forge_compare_to_spec_maps_arguments_and_returns_the_response() -> None:
    spec = AppSpec.model_validate(_golden("full"))
    flow = FakeFlowRepository()
    flow.results["get_draft"] = [FlowDraft.from_wire({})]
    settings = _settings(kf_dev_access_key_id="key-1", kf_dev_access_key_secret="s")
    async with Client(_server(settings, flow)) as client:
        result = await client.call_tool(
            "forge_compare_to_spec",
            {"flow_id": "F1", "spec": spec.model_dump(mode="json"), "app_id": "A1"},
        )
    assert flow.calls == [("get_draft", ("A1", "process", "F1"), {})]
    assert "ok" in result.structured_content
    assert set(result.structured_content) == {
        "ok",
        "mismatches",
        "checked",
        "ignored",
    }


@pytest.mark.asyncio
async def test_forge_compare_to_spec_fails_before_the_use_case_runs_with_no_key_pair() -> (  # noqa: E501
    None
):
    """Rule 23's other half: a LIVE tool refuses BEFORE the use case (and
    the port) ever runs when no key pair is available."""
    flow = FakeFlowRepository()
    settings = _settings(kf_dev_access_key_id=None, kf_dev_access_key_secret=None)
    async with Client(_server(settings, flow)) as client:
        with pytest.raises(ToolError):
            await client.call_tool(
                "forge_compare_to_spec",
                {"flow_id": "F1", "spec": _full_wire(), "app_id": "A1"},
            )
    assert flow.calls == []


# ---- full stateless round, driven only through the real tool boundary ---------------


@pytest.mark.asyncio
async def test_full_stateless_round_through_the_real_tool_boundary(
    tmp_path: Path,
) -> None:
    """questions -> update -> confirm -> approve -> plan, every step reading/
    writing ONLY plain dicts across the real MCP tool boundary -- proving
    the approval secret plumbing (lifespan -> AppResources -> both gate use
    cases) actually works end to end, not just in isolated unit tests."""
    async with Client(_server(_settings())) as client:
        opening = await client.call_tool("forge_intake_questions", {"limit": 2})
        assert [q["dimension"] for q in opening.structured_content["questions"]] == [
            1,
            1,
        ]

        patch = _full_wire()
        del patch["approved"]
        updated = await client.call_tool(
            "forge_update_spec", {"spec": None, "patch": patch}
        )
        assert updated.structured_content["gaps"] == []

        confirmation = await client.call_tool(
            "forge_request_confirmation",
            {"spec": updated.structured_content["spec"], "out_dir": str(tmp_path)},
        )
        assert confirmation.structured_content["gaps"] == []

        # the gate must still refuse before approval, even offered the plain digest
        with pytest.raises(ToolError):
            await client.call_tool(
                "forge_plan_app",
                {
                    "spec": updated.structured_content["spec"],
                    "approval_token": confirmation.structured_content["digest"],
                },
            )

        approval = await client.call_tool(
            "forge_approve_spec",
            {
                "spec": updated.structured_content["spec"],
                "digest": confirmation.structured_content["digest"],
                "decision": "approve",
            },
        )
        assert approval.structured_content["approved"] is True

        plan = await client.call_tool(
            "forge_plan_app",
            {
                "spec": approval.structured_content["spec"],
                "approval_token": approval.structured_content["approval_token"],
            },
        )
    assert plan.structured_content["op_count"] == 39


@pytest.mark.asyncio
async def test_full_round_reconstructs_an_appspec_equal_to_the_original_fixture(
    tmp_path: Path,
) -> None:
    """The other half of "stateless": decoding the FINAL wire spec straight back
    into a real AppSpec (bypassing the tools) must reproduce the ORIGINAL fixture
    object exactly, proving no tool in the chain silently mutated or lost anything
    along the way."""
    full = AppSpec.model_validate(_golden("full")).model_copy(
        update={"approved": False}
    )
    patch = full.model_dump(mode="json")
    del patch["approved"]
    async with Client(_server(_settings())) as client:
        step = await client.call_tool(
            "forge_update_spec", {"spec": None, "patch": patch}
        )
        confirmation = await client.call_tool(
            "forge_request_confirmation",
            {"spec": step.structured_content["spec"], "out_dir": str(tmp_path)},
        )
        approval = await client.call_tool(
            "forge_approve_spec",
            {
                "spec": step.structured_content["spec"],
                "digest": confirmation.structured_content["digest"],
                "decision": "approve",
            },
        )
    reconstructed = AppSpec.model_validate(approval.structured_content["spec"])
    assert isinstance(reconstructed, AppSpec)
    assert reconstructed == full.model_copy(update={"approved": True})
