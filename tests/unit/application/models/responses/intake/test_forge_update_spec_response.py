"""Tests for `ForgeUpdateSpecResponse` payload parity."""

from __future__ import annotations

from app.application.models.responses.intake.forge_update_spec_response import (
    ForgeUpdateSpecResponse,
)


def test_dump_matches_the_old_success_dict_key_set() -> None:
    response = ForgeUpdateSpecResponse(
        spec={"app_name": "X", "approved": False}, gaps=["1. a"], blocking_gaps=[]
    )
    assert response.model_dump(mode="json") == {
        "spec": {"app_name": "X", "approved": False},
        "gaps": ["1. a"],
        "blocking_gaps": [],
    }
