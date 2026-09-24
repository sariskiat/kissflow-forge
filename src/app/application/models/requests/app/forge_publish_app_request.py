"""app.application.models.requests.app.forge_publish_app_request — the DTO for
`forge_publish_app` (today's `server.py`: `publish_application_verified`,
`client.py`): publish an APPLICATION's draft to live.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ForgePublishAppRequest(BaseModel):
    """One `forge_publish_app` call.

    `app_id` is already resolved by the tool: the per-call `app_id`
    argument, else `settings.kf_app`, else `""` (see
    `brief_stage_d_common.md`, "The app id"). An empty value is a
    use-case-level refusal (`code=REFUSED`), not a DTO-level one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    app_id: str
