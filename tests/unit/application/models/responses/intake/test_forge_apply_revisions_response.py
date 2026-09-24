"""Tests for `ForgeApplyRevisionsResponse` payload parity."""

from __future__ import annotations

from app.application.models.responses.intake.forge_apply_revisions_response import (
    ForgeApplyRevisionsResponse,
)


def test_dump_matches_the_old_success_dict_key_set() -> None:
    response = ForgeApplyRevisionsResponse(
        spec={"app_name": "Y", "approved": False},
        digest="a" * 64,
        compiles=True,
        compile_error=None,
    )
    assert response.model_dump(mode="json") == {
        "spec": {"app_name": "Y", "approved": False},
        "digest": "a" * 64,
        "compiles": True,
        "compile_error": None,
    }
