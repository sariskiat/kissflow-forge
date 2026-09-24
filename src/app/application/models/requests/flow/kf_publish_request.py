"""Request DTO for `kf_publish`."""

from __future__ import annotations

from pydantic import BaseModel

from app.domain.value_objects.kinds import FlowKindArg


class KfPublishRequest(BaseModel):
    """`kf_publish`'s arguments, the app id already resolved.

    Attributes:
        flow_kind: The flow kind to publish.
        flow_id: The flow's id.
        app_id: The resolved app id: the tool's own `app_id` argument, else
            `settings.kf_app`, else `""`.
    """

    flow_kind: FlowKindArg
    flow_id: str
    app_id: str
