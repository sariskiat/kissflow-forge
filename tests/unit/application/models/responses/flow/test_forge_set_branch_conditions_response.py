"""`ForgeSetBranchConditionsResponse`: mirrors `BranchConditionReport.as_tool_result()`
minus `isError`, plus `snapshot_version`."""

from __future__ import annotations

from app.application.models.responses.flow.forge_set_branch_conditions_response import (
    ForgeSetBranchConditionsResponse,
)

# `app.infrastructure.kissflow.client.BranchConditionReport.as_tool_result()`'s
# own key set (pre-refactor) -- see fix-9 follow-up note in
# test_kf_apply_field_change_response.py.
OLD_KEYS = {
    "flow_id",
    "field_name",
    "branches",
    "verified",
    "missing",
    "uncovered",
    "meta_version",
    "published",
    "isError",
}


def test_model_dump_matches_the_old_success_dict_plus_snapshot_version() -> None:
    resp = ForgeSetBranchConditionsResponse(
        flow_id="F1",
        field_name="Track",
        branches=["Branch A", "Branch B"],
        verified=["Branch A", "Branch B"],
        missing=[],
        uncovered=["Gamma"],
        meta_version="v2",
        published=False,
        snapshot_version="v1",
    )
    got = resp.model_dump(mode="json")
    assert got == {
        "flow_id": "F1",
        "field_name": "Track",
        "branches": ["Branch A", "Branch B"],
        "verified": ["Branch A", "Branch B"],
        "missing": [],
        "uncovered": ["Gamma"],
        "meta_version": "v2",
        "published": False,
        "snapshot_version": "v1",
    }
    assert "isError" not in got


def test_snapshot_version_defaults_to_none() -> None:
    resp = ForgeSetBranchConditionsResponse(
        flow_id="F1",
        field_name="Track",
        branches=[],
        verified=[],
        missing=[],
        uncovered=[],
        meta_version=None,
        published=False,
    )
    assert resp.snapshot_version is None


def test_key_set_equals_old_success_dict_minus_iserror_plus_snapshot_version() -> None:
    resp = ForgeSetBranchConditionsResponse(
        flow_id="F1",
        field_name="Track",
        branches=["Branch A"],
        verified=["Branch A"],
        missing=[],
        uncovered=[],
        meta_version="v2",
        published=False,
        snapshot_version="v1",
    )
    assert set(resp.model_dump(mode="json")) == (OLD_KEYS - {"isError"}) | {
        "snapshot_version"
    }
