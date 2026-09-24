"""app.application.models.responses.flow.forge_set_branch_conditions_response
— the response DTO for `forge_set_branch_conditions`.

Fields mirror
`app.infrastructure.kissflow.client.BranchConditionReport.as_tool_result()`,
minus `isError`, plus `snapshot_version`. A branch that does NOT verify on
read-back is a failure (the shared brief's rule 7): the use case raises
`ApplicationError(code=VERIFY_FAILED)` instead of returning this DTO, so
`missing` is always empty on an actual response -- `uncovered` is a
different, non-error bucket and keeps its old shape unchanged.
"""

from __future__ import annotations

from pydantic import BaseModel


class ForgeSetBranchConditionsResponse(BaseModel):
    """The result of one fully-verified `forge_set_branch_conditions` call.

    Attributes:
        flow_id: The flow the conditions were written to.
        field_name: The deciding field.
        branches: Every branch name that was requested, in order.
        verified: The subset of `branches` confirmed present on read-back.
            Always equal to `branches` -- a shortfall raises instead of
            returning.
        missing: Always `[]` -- a non-empty value raises instead of
            returning.
        uncovered: Real Select options (when the deciding field is one) that,
            after this write, no branch on the gateway claims -- never an
            error on its own, only stated so it is never discovered later.
        meta_version: The draft's `_meta_version` after the write.
        published: Whether the flow was published by this call.
        snapshot_version: The draft version this write was planned against.
    """

    flow_id: str
    field_name: str
    branches: list[str]
    verified: list[str]
    missing: list[str]
    uncovered: list[str]
    meta_version: str | None
    published: bool
    snapshot_version: str | None = None
