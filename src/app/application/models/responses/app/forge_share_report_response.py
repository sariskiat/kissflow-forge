"""app.application.models.responses.app.forge_share_report_response — the DTO
for `forge_share_report`'s result: today's `client.apply_report_members`'s
success dict, minus `isError`, plus the additive `snapshot_version`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class ForgeShareReportResponse(BaseModel):
    """The (honestly unverifiable) audit of one `forge_share_report` call.

    `verified` is always `None`: no documented GET route exists for a
    report's own member list, so this is reported as "not independently
    read-back checked" rather than faking an audit it cannot perform.
    """

    model_config = ConfigDict(frozen=True)

    flow_id: str
    report_id: str
    requested: list[dict[str, Any]]
    posted: Any
    verified: None
    note: str
    snapshot_version: str | None = None
