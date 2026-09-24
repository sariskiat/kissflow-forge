"""Spec for app.application.models.responses.flow.forge_apply_layout_response."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.responses.flow.forge_apply_layout_response import (
    ForgeApplyLayoutResponse,
)

# `app.infrastructure.kissflow.client.ApplyReport.as_tool_result()`'s own key set
# (pre-refactor, `forge_apply_layout` reuses `ApplyReport`) -- see fix-9 follow-up
# note in test_kf_apply_field_change_response.py.
OLD_KEYS = {
    "flow_id",
    "added",
    "skipped",
    "verified",
    "missing",
    "changed_ignored",
    "collateral",
    "remediation",
    "meta_version",
    "published",
    "isError",
}


def _response(**overrides: object) -> ForgeApplyLayoutResponse:
    base: dict[str, object] = {
        "flow_id": "F1",
        "added": [],
        "skipped": ["Case Info"],
        "verified": ["Case Info"],
        "missing": [],
        "changed_ignored": [],
        "collateral": [],
        "remediation": [],
        "meta_version": "v2",
        "published": False,
    }
    base.update(overrides)
    return ForgeApplyLayoutResponse.model_validate(base)


def test_model_dump_json_mode_matches_the_old_success_dict_plus_snapshot_version() -> (
    None
):
    resp = _response(snapshot_version="v1")
    assert resp.model_dump(mode="json") == {
        "flow_id": "F1",
        "added": [],
        "skipped": ["Case Info"],
        "verified": ["Case Info"],
        "missing": [],
        "changed_ignored": [],
        "collateral": [],
        "remediation": [],
        "meta_version": "v2",
        "published": False,
        "snapshot_version": "v1",
    }


def test_snapshot_version_defaults_to_none() -> None:
    assert _response().snapshot_version is None


def test_key_set_equals_old_success_dict_minus_iserror_plus_snapshot_version() -> None:
    resp = _response(snapshot_version="v1")
    assert set(resp.model_dump(mode="json")) == (OLD_KEYS - {"isError"}) | {
        "snapshot_version"
    }


def test_is_frozen() -> None:
    resp = _response()
    with pytest.raises(ValidationError):
        resp.flow_id = "F2"  # type: ignore[misc]  # ty: ignore[invalid-assignment]
