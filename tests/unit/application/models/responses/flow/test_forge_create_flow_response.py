"""`ForgeCreateFlowResponse` -- the former `FlowCreateReport.as_tool_result()`
shape, minus `isError`, plus `snapshot_version`."""

from __future__ import annotations

from app.application.models.responses.flow.forge_create_flow_response import (
    ForgeCreateFlowResponse,
)

_BASE: dict[str, object] = {
    "kind": "list",
    "flow_id": "L1",
    "name": "Priorities",
    "status": "Live",
    "born_live": True,
    "from_template": False,
    "template_sections": [],
    "template_required_fields": [],
    "template_steps": [],
    "template_read_error": None,
}


def test_equals_todays_success_dict_plus_snapshot_version() -> None:
    """The old dict left `note` out entirely when neither `from_template` nor
    `template_read_error` applied (`FlowCreateReport.as_tool_result()`'s own
    `if`/`elif`, never a bare `out["note"] = None`) -- the response DTO does the
    same (brief_stage_d_common.md lesson 15)."""
    resp = ForgeCreateFlowResponse.model_validate({**_BASE, "snapshot_version": None})
    assert resp.model_dump(mode="json") == {
        **_BASE,
        "snapshot_version": None,
    }


def test_note_and_snapshot_version_default_to_none() -> None:
    resp = ForgeCreateFlowResponse.model_validate(_BASE)
    assert resp.note is None
    assert resp.snapshot_version is None
