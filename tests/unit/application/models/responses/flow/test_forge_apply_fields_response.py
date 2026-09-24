"""Spec for app.application.models.responses.flow.forge_apply_fields_response."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.models.responses.flow.forge_apply_fields_response import (
    ForgeApplyFieldsResponse,
)

# `app.infrastructure.kissflow.client.FullFieldsReport.as_tool_result()`'s own key
# set (pre-refactor) -- the coordinator's fix-9 follow-up: a key-set comparison
# against `model_fields` cannot catch a DTO that gained or lost a key relative to
# the old dict, so this is the literal old set, checked by name.
OLD_KEYS = {
    "flow_id",
    "added",
    "skipped",
    "verified",
    "missing",
    "changed_ignored",
    "collateral",
    "remediation",
    "validations_verified",
    "validations_missing",
    "computed_verified",
    "computed_missing",
    "conditional_verified",
    "conditional_missing",
    "meta_version",
    "published",
    "isError",
}


def _response(**overrides: object) -> ForgeApplyFieldsResponse:
    base: dict[str, object] = {
        "flow_id": "F1",
        "added": ["A"],
        "skipped": [],
        "verified": ["A"],
        "missing": [],
        "changed_ignored": [],
        "collateral": [],
        "remediation": [],
        "validations_verified": [],
        "validations_missing": [],
        "computed_verified": [],
        "computed_missing": [],
        "conditional_verified": [],
        "conditional_missing": [],
        "meta_version": "v2",
        "published": False,
    }
    base.update(overrides)
    return ForgeApplyFieldsResponse.model_validate(base)


def test_model_dump_json_mode_matches_the_old_success_dict_plus_snapshot_version() -> (
    None
):
    resp = _response(snapshot_version="v1")
    dumped = resp.model_dump(mode="json")
    assert dumped["flow_id"] == "F1"
    assert dumped["added"] == ["A"]
    assert dumped["snapshot_version"] == "v1"
    assert "isError" not in dumped


def test_key_set_equals_old_success_dict_minus_iserror_plus_snapshot_version() -> None:
    """Fix 9's return-shape rule, made precise: a `model_fields` comparison
    cannot catch a DTO key that the old `FullFieldsReport.as_tool_result()`
    dict did not have, or a key it had that the DTO dropped. Compare against
    the literal old key set instead."""
    resp = _response(snapshot_version="v1")
    assert set(resp.model_dump(mode="json")) == (OLD_KEYS - {"isError"}) | {
        "snapshot_version"
    }


def test_snapshot_version_defaults_to_none() -> None:
    assert _response().snapshot_version is None


def test_is_frozen() -> None:
    resp = _response()
    with pytest.raises(ValidationError):
        resp.flow_id = "F2"  # type: ignore[misc]  # ty: ignore[invalid-assignment]
