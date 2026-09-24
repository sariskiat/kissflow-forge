"""app.application.models.responses.app.forge_publish_app_response — the DTO for
`forge_publish_app`'s result: today's `client.publish_application_verified`'s
success dict, minus `isError`, plus the additive `snapshot_version`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ForgePublishAppResponse(BaseModel):
    """The post-publish read-back audit of one `forge_publish_app` call.

    `runtime_id` is `None`, with `note` stating why, when no `Runtime_`-
    prefixed node was observed on the read-back -- that shape is UNCAPTURED
    on this tenant (never guessed).
    """

    model_config = ConfigDict(frozen=True)

    app_id: str
    published: bool
    runtime_id: str | None
    meta_version: str | None
    note: str | None
    snapshot_version: str | None = None
