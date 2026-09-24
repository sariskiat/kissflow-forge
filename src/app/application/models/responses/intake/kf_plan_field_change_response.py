"""app.application.models.responses.intake.kf_plan_field_change_response -- the
DTO for `kf_plan_field_change`'s result: today's `tools.plan_field_change`
success dict, minus `isError` (this tool never writes, so no
`snapshot_version` either).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class AddedField(BaseModel):
    """One field `kf_apply_field_change` would create."""

    model_config = ConfigDict(frozen=True)

    name: str
    type: str
    required: bool


class EditedField(BaseModel):
    """One field `kf_apply_field_change` would edit (by id)."""

    model_config = ConfigDict(frozen=True)

    name: str


class KfPlanFieldChangeResponse(BaseModel):
    """The dry-run preview of one `kf_plan_field_change` call."""

    model_config = ConfigDict(frozen=True)

    adds: list[AddedField]
    edits: list[EditedField]
    skipped: list[str]
    human_readable: str
