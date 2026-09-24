"""app.application.models.responses.app.forge_create_template_app_response — the
DTO for `forge_create_template_app`'s result: today's `client.
create_template_app`'s success dict, minus `isError`, plus the additive
`snapshot_version`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class ForgeCreateTemplateAppResponse(BaseModel):
    """The full audit of one ONE-call Template App build: the created
    application/role/process ids, the member-grant report, the process and
    app publish read-backs, the doctor read-back, and the (unverified)
    builder URLs.
    """

    model_config = ConfigDict(frozen=True)

    app_id: str
    name: str
    flow_id: str
    role_id: str
    role_name: str
    members: dict[str, Any]
    process_status: str | None
    app_publish: dict[str, Any]
    doctor: dict[str, Any]
    app_url: str
    process_url: str
    url_verified: bool
    graph_nodes_verified: int
    snapshot_version: str | None = None
