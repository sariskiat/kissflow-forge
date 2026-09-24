"""Tests for `ForgeRequestConfirmationResponse` payload parity."""

from __future__ import annotations

from app.application.models.responses.intake.forge_request_confirmation_response import (  # noqa: E501
    ForgeRequestConfirmationResponse,
)


def test_dump_matches_the_old_success_dict_key_set() -> None:
    response = ForgeRequestConfirmationResponse(
        digest="a" * 64,
        artifact_paths={"design.html": "/tmp/design.html"},
        questions=["ok?"],
        gaps=[],
        blocking_gaps=[],
    )
    assert response.model_dump(mode="json") == {
        "digest": "a" * 64,
        "artifact_paths": {"design.html": "/tmp/design.html"},
        "questions": ["ok?"],
        "gaps": [],
        "blocking_gaps": [],
    }
