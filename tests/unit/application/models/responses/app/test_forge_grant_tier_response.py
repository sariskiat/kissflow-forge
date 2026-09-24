"""Spec for app.application.models.responses.app.forge_grant_tier_response."""

from __future__ import annotations

from app.application.models.responses.app.forge_grant_tier_response import (
    ForgeGrantTierResponse,
)


def test_model_dump_json_mode_is_a_plain_json_safe_dict() -> None:
    resp = ForgeGrantTierResponse(
        flow_id="F1", kind="process", role_id="R1", tier="Manage", verified=True
    )
    assert resp.model_dump(mode="json") == {
        "flow_id": "F1",
        "kind": "process",
        "role_id": "R1",
        "tier": "Manage",
        "verified": True,
        "snapshot_version": None,
    }


def test_model_validate_round_trips() -> None:
    original = ForgeGrantTierResponse(
        flow_id="F1", kind="case", role_id="R1", tier="Edit", verified=True
    )
    got = ForgeGrantTierResponse.model_validate(original.model_dump(mode="json"))
    assert got == original
