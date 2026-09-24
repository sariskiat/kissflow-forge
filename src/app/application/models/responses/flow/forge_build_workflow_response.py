"""app.application.models.responses.flow.forge_build_workflow_response — the
response DTO for `forge_build_workflow`.

Fields mirror `app.infrastructure.kissflow.client.WorkflowReport.as_tool_result()`,
minus `isError` (G6: a real failure now raises `ToolError` instead of riding
inside a successful payload) plus `snapshot_version` (every write tool, spec
section 6, G11's invariant). A step that does NOT verify on read-back is a
failure (the shared brief's rule 7): the use case raises
`ApplicationError(code=VERIFY_FAILED)` instead of returning this DTO, so
`missing_steps` is always empty on an actual response.
"""

from __future__ import annotations

from pydantic import BaseModel


class ForgeBuildWorkflowResponse(BaseModel):
    """The result of one fully-verified `forge_build_workflow` call.

    Attributes:
        flow_id: The flow that was rebuilt.
        steps: Every step name that was requested, in order.
        verified_steps: The subset of `steps` confirmed present on read-back.
            Always equal to `steps` -- a shortfall raises instead of
            returning.
        missing_steps: Always `[]` -- a non-empty value raises instead of
            returning.
        assigned: Step names that got a real Resource/assignee wired.
        unassigned: Step names with no assignee to wire.
        permissions_deleted: How many Permission nodes this rebuild destroyed,
            counted on the read-back, never on the offline plan.
        collateral: Everything else this rebuild destroyed or relocated that
            the caller never named (a wiped Permission matrix, a relocated
            SequenceNumber step stamp, a malformed Permission node).
        remediation: Tool names the caller now owes because of `collateral`.
        meta_version: The draft's `_meta_version` after the write.
        published: Whether the flow was published by this call.
        snapshot_version: The draft version this write was planned against.
    """

    flow_id: str
    steps: list[str]
    verified_steps: list[str]
    missing_steps: list[str]
    assigned: list[str]
    unassigned: list[str]
    permissions_deleted: int
    collateral: list[str]
    remediation: list[str]
    meta_version: str | None
    published: bool
    snapshot_version: str | None = None
