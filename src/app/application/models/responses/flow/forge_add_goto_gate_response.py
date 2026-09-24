"""app.application.models.responses.flow.forge_add_goto_gate_response — the
response DTO for `forge_add_goto_gate`.

Fields mirror `app.infrastructure.kissflow.client.GotoGateReport.as_tool_result()`,
minus `isError`, plus `snapshot_version`. A loop condition that does NOT verify
on read-back is a failure (the shared brief's rule 7): the use case raises
`ApplicationError(code=VERIFY_FAILED)` instead of returning this DTO, so
`goto_activity_id` is never `None` on an actual response -- unlike the old
dict, which carried `None` there on its own `isError: true` path.
"""

from __future__ import annotations

from pydantic import BaseModel


class ForgeAddGotoGateResponse(BaseModel):
    """The result of one successfully verified `forge_add_goto_gate` call.

    Attributes:
        flow_id: The flow the gate was added to.
        goto_activity_id: The new GotoTask's node id.
        target_activity: The workflow step the GotoTask jumps back to.
        field_name: The Boolean field the loop condition tests.
        branch_name: The branch the GotoTask was scoped to, or `None`.
        verified: Whether the loop condition was confirmed on read-back.
            Always `True` -- a `False` value raises instead of returning.
        meta_version: The draft's `_meta_version` after the write.
        published: Whether the flow was published by this call.
        snapshot_version: The draft version this write was planned against.
    """

    flow_id: str
    goto_activity_id: str
    target_activity: str
    field_name: str
    branch_name: str | None
    verified: bool
    meta_version: str | None
    published: bool
    snapshot_version: str | None = None
