"""Request DTO for `kf_get_flow_schema`."""

from __future__ import annotations

from pydantic import BaseModel

from app.domain.value_objects.kinds import SchemaKind


class KfGetFlowSchemaRequest(BaseModel):
    """`kf_get_flow_schema`'s arguments, the app id already resolved.

    Attributes:
        flow_kind: The kind of draft to read. `"page"` needs `app_id`.
        flow_id: The flow's (or, for `"page"`, the page's) id.
        app_id: The resolved app id: the tool's own `app_id` argument, else
            `settings.kf_app`, else `""`.
        app_id_given: Whether the caller passed a non-empty `app_id`
            argument -- a page draft lives under its owning application,
            never a hard-coded `KF_APP` default, so a page read is refused
            unless this is `True`, even when `app_id` above was filled in
            from `settings.kf_app`.
    """

    flow_kind: SchemaKind
    flow_id: str
    app_id: str
    app_id_given: bool
