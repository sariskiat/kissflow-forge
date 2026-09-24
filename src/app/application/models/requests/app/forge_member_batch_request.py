"""Request DTO for `forge_member_batch`."""

from __future__ import annotations

from pydantic import BaseModel

from app.domain.value_objects.kinds import FlowKindArg


class ForgeMemberBatchRequest(BaseModel):
    """One `forge_member_batch` call.

    Attributes:
        target_flow_id: The flow to grant members onto.
        source_flow_id: The flow to harvest members from, or `None` to
            auto-discover one.
        kind: Both flows' kind.
        app_id: The resolved application id (never empty by the time the
            use case reads it successfully; see `require_app_id`).
    """

    target_flow_id: str
    source_flow_id: str | None = None
    kind: FlowKindArg = "process"
    app_id: str
