"""app.application.models.requests.flow.forge_set_visibility_request — the
request DTO for `forge_set_visibility`."""

from __future__ import annotations

from pydantic import BaseModel

from app.domain.value_objects.kinds import FlowKind


class ForgeSetVisibilityRequest(BaseModel):
    """One `forge_set_visibility` call: rebuild a process's per-step visibility.

    Attributes:
        flow_id: The flow to rebuild visibility on.
        owners: Section name -> the step names that own it (section-level).
        field_owners: Field name -> the step names it is Editable at
            (field-level override), or `None` for section-level only.
        kind: The flow kind.
        publish: Publish the flow once the matrix is written and verified.
        include_pairs: Return every (column, activity) pair in full instead
            of the bounded counts + rollups.
        app_id: The resolved application id. Empty means "no app selected".
    """

    flow_id: str
    owners: dict[str, list[str]]
    field_owners: dict[str, list[str]] | None = None
    kind: FlowKind = "process"
    publish: bool = False
    include_pairs: bool = False
    app_id: str = ""
