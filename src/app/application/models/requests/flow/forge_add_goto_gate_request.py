"""app.application.models.requests.flow.forge_add_goto_gate_request — the
request DTO for `forge_add_goto_gate`."""

from __future__ import annotations

from pydantic import BaseModel

from app.domain.value_objects.kinds import FlowKind


class ForgeAddGotoGateRequest(BaseModel):
    """One `forge_add_goto_gate` call: add a backward-jump GotoTask, gated on a
    Boolean field.

    Attributes:
        flow_id: The flow to add the gate to.
        target_activity_name: The workflow step the GotoTask jumps back to.
        field_name: The Boolean field the loop condition tests.
        branch_name: Scopes `target_activity_name` (and the new GotoTask) to
            one branch of the flow's single Parallel gateway.
        kind: The flow kind.
        publish: Publish the flow once the gate is written and verified.
        app_id: The resolved application id. Empty means "no app selected".
    """

    flow_id: str
    target_activity_name: str
    field_name: str
    branch_name: str | None = None
    kind: FlowKind = "process"
    publish: bool = False
    app_id: str = ""
