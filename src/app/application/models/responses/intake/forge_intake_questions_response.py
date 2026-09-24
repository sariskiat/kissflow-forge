"""app.application.models.responses.intake.forge_intake_questions_response --
the DTO for `forge_intake_questions`'s result.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class IntakeQuestion(BaseModel):
    """One question, with the dimension it belongs to attached.

    A caller restricted to MCP has no other way to learn which of the 11
    dimensions a given question id belongs to.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    dimension: int
    dimension_name: str
    text_th: str
    why: str
    example: str
    follow_ups: list[str]


class ForgeIntakeQuestionsResponse(BaseModel):
    """The next questions to ask, plus the spec's current gap lists.

    `spec` always carries `approved: false`, regardless of what the input
    spec's was -- this tool is a read step, never a place `approved` should
    survive a round trip unexamined.
    """

    model_config = ConfigDict(frozen=True)

    questions: list[IntakeQuestion]
    gaps: list[str]
    blocking_gaps: list[str]
    spec: dict[str, Any]
