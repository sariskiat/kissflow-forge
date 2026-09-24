"""Response DTO for `kf_publish`."""

from __future__ import annotations

from pydantic import BaseModel


class KfPublishResponse(BaseModel):
    """`kf_publish`'s success result.

    Attributes:
        published: Always `True` on success.
        flow_id: The published flow's id.
        snapshot_version: The draft version read before publishing (spec
            G11's additive field; today's tool carries no such key).
    """

    published: bool
    flow_id: str
    snapshot_version: str | None = None
