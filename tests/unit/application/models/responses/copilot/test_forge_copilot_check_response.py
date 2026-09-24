"""Spec for app.application.models.responses.copilot.forge_copilot_check_response."""

from __future__ import annotations

from app.application.models.responses.copilot.forge_copilot_check_response import (
    ForgeCopilotCheckResponse,
)


def test_model_dump_matches_the_old_success_dict_shape() -> None:
    resp = ForgeCopilotCheckResponse(
        app_id="A1",
        conversation_id="C1",
        reply="done",
        scatter={},
        landed_nodes={},
    )
    dumped = resp.model_dump(mode="json")
    assert dumped["reply"] == "done"
    assert dumped["reply_is_proof"] is False
    assert dumped["scatter"] == {}
    assert dumped["landed_nodes"] == {}
    assert "THE RULE" in dumped["note"]


def test_the_key_set_has_no_ok_field() -> None:
    """The old `CopilotCheckReport.as_tool_result()` (without `isError`) has no
    `ok` key -- a reply being present is never proof of anything (THE RULE),
    so the response never carries a verdict key the old dict did not have
    (correction, 2026-09-23)."""
    resp = ForgeCopilotCheckResponse(
        app_id="A1",
        conversation_id="C1",
        reply=None,
        scatter={},
        landed_nodes={},
    )
    dumped = resp.model_dump(mode="json")
    assert set(dumped) == {
        "app_id",
        "conversation_id",
        "reply",
        "reply_is_proof",
        "scatter",
        "landed_nodes",
        "note",
    }
