"""app.application.models.responses.flow.forge_add_field_validation_response
— the `forge_add_field_validation` response DTO.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ForgeAddFieldValidationResponse(BaseModel):
    """The output-invariant audit for `forge_add_field_validation`: every
    requested rule lands in exactly one of `verified` / `missing`."""

    model_config = ConfigDict(frozen=True)

    flow_id: str
    field_name: str
    rules: list[tuple[str, str]]
    verified: list[tuple[str, str]]
    missing: list[tuple[str, str]]
    meta_version: str | None
    published: bool
    snapshot_version: str | None = None
