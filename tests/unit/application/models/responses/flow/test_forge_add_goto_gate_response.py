"""`ForgeAddGotoGateResponse`: mirrors `GotoGateReport.as_tool_result()` minus
`isError`, plus `snapshot_version`. Rule 7: a gate that does not verify raises
`ApplicationError` in the use case instead of reaching this DTO, so
`goto_activity_id` is a plain `str`, never `None`, here."""

from __future__ import annotations

from app.application.models.responses.flow.forge_add_goto_gate_response import (
    ForgeAddGotoGateResponse,
)

# `app.infrastructure.kissflow.client.GotoGateReport.as_tool_result()`'s own key
# set (pre-refactor) -- see fix-9 follow-up note in
# test_kf_apply_field_change_response.py.
OLD_KEYS = {
    "flow_id",
    "goto_activity_id",
    "target_activity",
    "field_name",
    "branch_name",
    "verified",
    "meta_version",
    "published",
    "isError",
}


def test_model_dump_matches_the_old_success_dict_plus_snapshot_version() -> None:
    resp = ForgeAddGotoGateResponse(
        flow_id="F1",
        goto_activity_id="Activity_Goto1",
        target_activity="Review",
        field_name="Done Flag",
        branch_name=None,
        verified=True,
        meta_version="v2",
        published=False,
        snapshot_version="v1",
    )
    got = resp.model_dump(mode="json")
    assert got == {
        "flow_id": "F1",
        "goto_activity_id": "Activity_Goto1",
        "target_activity": "Review",
        "field_name": "Done Flag",
        "branch_name": None,
        "verified": True,
        "meta_version": "v2",
        "published": False,
        "snapshot_version": "v1",
    }
    assert "isError" not in got


def test_snapshot_version_defaults_to_none() -> None:
    resp = ForgeAddGotoGateResponse(
        flow_id="F1",
        goto_activity_id="Activity_Goto1",
        target_activity="Review",
        field_name="Done Flag",
        branch_name=None,
        verified=True,
        meta_version=None,
        published=False,
    )
    assert resp.snapshot_version is None


def test_key_set_equals_old_success_dict_minus_iserror_plus_snapshot_version() -> None:
    resp = ForgeAddGotoGateResponse(
        flow_id="F1",
        goto_activity_id="Activity_Goto1",
        target_activity="Review",
        field_name="Done Flag",
        branch_name=None,
        verified=True,
        meta_version="v2",
        published=False,
        snapshot_version="v1",
    )
    assert set(resp.model_dump(mode="json")) == (OLD_KEYS - {"isError"}) | {
        "snapshot_version"
    }
