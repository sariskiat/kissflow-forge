"""Request DTO for `forge_delete_flow`."""

from __future__ import annotations

from pydantic import BaseModel

from app.domain.value_objects.kinds import DeleteKind


class ForgeDeleteFlowRequest(BaseModel):
    """`forge_delete_flow`'s arguments, the app id already resolved.

    Attributes:
        kind: What to delete.
        flow_id: The target's id (for `kind="application"`, the app id
            itself).
        app_id: The resolved app id: the tool's own `app_id` argument, else
            `settings.kf_app`, else `""`. Unused for `kind="application"`.
        app_id_given: Whether the caller passed a non-empty `app_id`
            argument -- a page delete is refused unless this is `True`,
            even when `app_id` above was filled in from `settings.kf_app`.
    """

    kind: DeleteKind
    flow_id: str
    app_id: str
    app_id_given: bool
