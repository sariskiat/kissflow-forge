"""`ForgeAddFieldValidationResponse`: `model_dump(mode="json")` equals
today's `ValidationReport.as_tool_result()` (pre-refactor) without
`isError`, plus `snapshot_version`."""

from __future__ import annotations

from app.application.models.responses.flow.forge_add_field_validation_response import (
    ForgeAddFieldValidationResponse,
)

# `app.infrastructure.kissflow.client.ValidationReport.as_tool_result()`'s own
# key set (pre-refactor) -- see fix-9 follow-up note in
# test_kf_apply_field_change_response.py.
OLD_KEYS = {
    "flow_id",
    "field_name",
    "rules",
    "verified",
    "missing",
    "meta_version",
    "published",
    "isError",
}


def test_model_dump_matches_the_old_success_dict_plus_snapshot_version() -> None:
    resp = ForgeAddFieldValidationResponse(
        flow_id="F1",
        field_name="Notes",
        rules=[("CONTAINS", "important"), ("MAX_LENGTH", "200")],
        verified=[("CONTAINS", "important"), ("MAX_LENGTH", "200")],
        missing=[],
        meta_version="v2",
        published=False,
        snapshot_version="v1",
    )
    assert resp.model_dump(mode="json") == {
        "flow_id": "F1",
        "field_name": "Notes",
        "rules": [["CONTAINS", "important"], ["MAX_LENGTH", "200"]],
        "verified": [["CONTAINS", "important"], ["MAX_LENGTH", "200"]],
        "missing": [],
        "meta_version": "v2",
        "published": False,
        "snapshot_version": "v1",
    }


def test_snapshot_version_defaults_to_none() -> None:
    resp = ForgeAddFieldValidationResponse(
        flow_id="F1",
        field_name="Notes",
        rules=[],
        verified=[],
        missing=[],
        meta_version=None,
        published=False,
    )
    assert resp.snapshot_version is None


def test_key_set_equals_old_success_dict_minus_iserror_plus_snapshot_version() -> None:
    resp = ForgeAddFieldValidationResponse(
        flow_id="F1",
        field_name="Notes",
        rules=[("CONTAINS", "important")],
        verified=[("CONTAINS", "important")],
        missing=[],
        meta_version="v2",
        published=False,
        snapshot_version="v1",
    )
    assert set(resp.model_dump(mode="json")) == (OLD_KEYS - {"isError"}) | {
        "snapshot_version"
    }
