"""app.application.models.requests.flow.forge_add_sequence_number_request —
the `forge_add_sequence_number` request DTO.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.domain.value_objects.kinds import FlowKind


class ForgeAddSequenceNumberRequest(BaseModel):
    """Shape for `forge_add_sequence_number`: an auto-numbered item-id field,
    its host section, its stamp format, and the step it stamps at."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    flow_id: str
    field_name: str
    section_name: str
    prefix: str
    padding: str
    step_activity_name: str
    start: int = 0
    end: int = 2
    kind: FlowKind = "process"
    publish: bool = False
    app_id: str
