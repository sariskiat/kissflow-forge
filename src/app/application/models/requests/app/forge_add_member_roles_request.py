"""Request DTO for `forge_add_member_roles`."""

from __future__ import annotations

from pydantic import BaseModel

from app.domain.value_objects.kinds import FlowKindArg


class ForgeAddMemberRolesRequest(BaseModel):
    """One `forge_add_member_roles` call.

    Attributes:
        target_flow_id: The flow to grant the roles onto.
        roles: `{caller_id: display_name}` -- matched and, when missing,
            created by `display_name`, scoped to `app_id`.
        kind: The target flow's kind.
        app_id: The resolved application id.
    """

    target_flow_id: str
    roles: dict[str, str]
    kind: FlowKindArg = "process"
    app_id: str
