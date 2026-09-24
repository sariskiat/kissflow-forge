"""`ForgeBuildWorkflowResponse`: mirrors `WorkflowReport.as_tool_result()` minus
`isError`, plus `snapshot_version`."""

from __future__ import annotations

from typing import Any

from app.application.models.responses.flow.forge_build_workflow_response import (
    ForgeBuildWorkflowResponse,
)

# `app.infrastructure.kissflow.client.WorkflowReport.as_tool_result()`'s own key
# set (pre-refactor) -- see fix-9 follow-up note in
# test_kf_apply_field_change_response.py.
OLD_KEYS = {
    "flow_id",
    "steps",
    "verified_steps",
    "missing_steps",
    "assigned",
    "unassigned",
    "permissions_deleted",
    "collateral",
    "remediation",
    "meta_version",
    "published",
    "isError",
}


def _response(**overrides: Any) -> ForgeBuildWorkflowResponse:
    values: dict[str, Any] = {
        "flow_id": "F1",
        "steps": ["Draft", "Review"],
        "verified_steps": ["Draft", "Review"],
        "missing_steps": [],
        "assigned": ["Draft"],
        "unassigned": ["Review"],
        "permissions_deleted": 0,
        "collateral": [],
        "remediation": [],
        "meta_version": "v2",
        "published": False,
    }
    values.update(overrides)
    return ForgeBuildWorkflowResponse(**values)


def test_model_dump_matches_the_old_success_dict_plus_snapshot_version() -> None:
    resp = _response(snapshot_version="v1")
    got = resp.model_dump(mode="json")
    assert got == {
        "flow_id": "F1",
        "steps": ["Draft", "Review"],
        "verified_steps": ["Draft", "Review"],
        "missing_steps": [],
        "assigned": ["Draft"],
        "unassigned": ["Review"],
        "permissions_deleted": 0,
        "collateral": [],
        "remediation": [],
        "meta_version": "v2",
        "published": False,
        "snapshot_version": "v1",
    }
    assert "isError" not in got


def test_snapshot_version_defaults_to_none() -> None:
    resp = _response()
    assert resp.snapshot_version is None
    assert resp.model_dump(mode="json")["snapshot_version"] is None


def test_key_set_equals_old_success_dict_minus_iserror_plus_snapshot_version() -> None:
    resp = _response(snapshot_version="v1")
    assert set(resp.model_dump(mode="json")) == (OLD_KEYS - {"isError"}) | {
        "snapshot_version"
    }
