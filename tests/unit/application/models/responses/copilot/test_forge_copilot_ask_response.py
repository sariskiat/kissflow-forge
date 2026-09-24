"""Spec for app.application.models.responses.copilot.forge_copilot_ask_response."""

from __future__ import annotations

from app.application.models.responses.copilot.forge_copilot_ask_response import (
    ForgeCopilotAskResponse,
)


def test_model_dump_matches_the_old_success_dict_plus_snapshot_version() -> None:
    resp = ForgeCopilotAskResponse(
        app_id="A1",
        message="add a field",
        conversation_id="C1",
        immediate_reply="which step?",
        expect=[],
        status="matched",
    )
    dumped = resp.model_dump(mode="json")
    assert dumped["conversation_id"] == "C1"
    assert dumped["immediate_reply"] == "which step?"
    assert dumped["reply_is_proof"] is False
    assert dumped["status"] == "matched"
    assert "THE RULE" in dumped["note"]
    assert dumped["snapshot_version"] is None


def test_reply_is_proof_is_always_false() -> None:
    resp = ForgeCopilotAskResponse(
        app_id="A1",
        message="add a field",
        conversation_id=None,
        immediate_reply=None,
        expect=[],
        status="pending: ...",
    )
    assert resp.reply_is_proof is False
