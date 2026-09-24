"""Tests for `ForgeIntakeQuestionsResponse` payload parity."""

from __future__ import annotations

from app.application.models.responses.intake.forge_intake_questions_response import (
    ForgeIntakeQuestionsResponse,
    IntakeQuestion,
)


def test_dump_matches_the_old_success_dict_key_set() -> None:
    response = ForgeIntakeQuestionsResponse(
        questions=[
            IntakeQuestion(
                id="1a",
                dimension=1,
                dimension_name="problem/goal",
                text_th="?",
                why="because",
                example="e.g.",
                follow_ups=["f1"],
            )
        ],
        gaps=["1. problem/goal: ..."],
        blocking_gaps=["1. problem/goal: ..."],
        spec={"app_name": "", "approved": False},
    )
    assert response.model_dump(mode="json") == {
        "questions": [
            {
                "id": "1a",
                "dimension": 1,
                "dimension_name": "problem/goal",
                "text_th": "?",
                "why": "because",
                "example": "e.g.",
                "follow_ups": ["f1"],
            }
        ],
        "gaps": ["1. problem/goal: ..."],
        "blocking_gaps": ["1. problem/goal: ..."],
        "spec": {"app_name": "", "approved": False},
    }
