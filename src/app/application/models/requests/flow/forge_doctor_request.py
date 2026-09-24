"""Request DTO for `forge_doctor`."""

from __future__ import annotations

from pydantic import BaseModel

from app.domain.value_objects.kinds import FlowKindArg


class ForgeDoctorRequest(BaseModel):
    """`forge_doctor`'s arguments, the app id already resolved.

    Attributes:
        flow_id: The flow's id.
        kind: The flow kind.
        visibility_role_claims: The plan's doctor-op role-scoped visibility
            claims, passed through verbatim; each one always fails the
            audit.
        app_id: The resolved app id: the tool's own `app_id` argument, else
            `settings.kf_app`, else `""`.
    """

    flow_id: str
    kind: FlowKindArg = "process"
    visibility_role_claims: list[str] | None = None
    app_id: str
