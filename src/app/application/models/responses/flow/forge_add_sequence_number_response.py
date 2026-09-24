"""app.application.models.responses.flow.forge_add_sequence_number_response
— the `forge_add_sequence_number` response DTO.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ForgeAddSequenceNumberResponse(BaseModel):
    """The read-back audit for `forge_add_sequence_number`: whether the
    SequenceNumber field and its 3 Property nodes landed."""

    model_config = ConfigDict(frozen=True)

    flow_id: str
    field_name: str
    section: str
    verified: bool
    missing: bool
    meta_version: str | None
    published: bool
    snapshot_version: str | None = None
