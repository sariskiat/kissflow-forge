"""app.application.models.requests.flow.forge_set_branch_conditions_request —
the request DTO for `forge_set_branch_conditions`."""

from __future__ import annotations

from pydantic import BaseModel

from app.domain.value_objects.kinds import FlowKind


class ForgeSetBranchConditionsRequest(BaseModel):
    """One `forge_set_branch_conditions` call: make a Parallel's branches
    conditional on one field.

    Attributes:
        flow_id: The flow to rewrite branch conditions on.
        field_name: The deciding field.
        branch_literals: Branch name -> the literal that fires it.
        kind: The flow kind.
        publish: Publish the flow once the conditions are written and
            verified.
        app_id: The resolved application id. Empty means "no app selected".
    """

    flow_id: str
    field_name: str
    branch_literals: dict[str, str]
    kind: FlowKind = "process"
    publish: bool = False
    app_id: str = ""
