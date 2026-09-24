"""app.application.models.responses.intake.forge_request_confirmation_response
-- the DTO for `forge_request_confirmation`'s result.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ForgeRequestConfirmationResponse(BaseModel):
    """The confirmation pack: a content digest, the written artifact paths,
    and one plain-language question per risky choice the spec makes."""

    model_config = ConfigDict(frozen=True)

    digest: str
    artifact_paths: dict[str, str]
    questions: list[str]
    gaps: list[str]
    blocking_gaps: list[str]
