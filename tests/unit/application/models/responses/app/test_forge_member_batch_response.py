"""Spec for app.application.models.responses.app.forge_member_batch_response."""

from __future__ import annotations

from app.application.models.responses.app.forge_member_batch_response import (
    ForgeMemberBatchResponse,
)


def _response() -> ForgeMemberBatchResponse:
    return ForgeMemberBatchResponse(
        target_flow_id="F1",
        source_flow_id="F2",
        harvested=["Ro_front_001"],
        applied=["Ro_front_001"],
        verified=["Ro_front_001"],
        missing=[],
        note=None,
        role_ids=["m1"],
        resolved={},
        roles_seen=1,
        roles_granted=1,
        roles_unusable=[],
    )


def test_snapshot_version_defaults_to_none() -> None:
    assert _response().snapshot_version is None


def test_model_dump_json_mode_is_a_plain_json_safe_dict() -> None:
    assert _response().model_dump(mode="json") == {
        "target_flow_id": "F1",
        "source_flow_id": "F2",
        "harvested": ["Ro_front_001"],
        "applied": ["Ro_front_001"],
        "verified": ["Ro_front_001"],
        "missing": [],
        "note": None,
        "role_ids": ["m1"],
        "resolved": {},
        "roles_seen": 1,
        "roles_granted": 1,
        "roles_unusable": [],
        "snapshot_version": None,
    }


def test_model_validate_round_trips() -> None:
    original = _response()
    got = ForgeMemberBatchResponse.model_validate(original.model_dump(mode="json"))
    assert got == original
