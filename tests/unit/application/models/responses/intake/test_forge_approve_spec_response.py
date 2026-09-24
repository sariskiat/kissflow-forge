"""Tests for `ForgeApproveSpecResponse` payload parity."""

from __future__ import annotations

from app.application.models.responses.intake.forge_approve_spec_response import (
    ForgeApproveSpecResponse,
)


def test_dump_matches_the_old_success_dict_key_set() -> None:
    response = ForgeApproveSpecResponse(
        spec={"app_name": "X", "approved": True},
        approved=True,
        digest="a" * 64,
        approval_token="b" * 64,
    )
    assert response.model_dump(mode="json") == {
        "spec": {"app_name": "X", "approved": True},
        "approved": True,
        "digest": "a" * 64,
        "approval_token": "b" * 64,
    }
