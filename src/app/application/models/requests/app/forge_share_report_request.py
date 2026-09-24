"""app.application.models.requests.app.forge_share_report_request — the DTO for
`forge_share_report` (today's `server.py`: `apply_report_members`, `client.py`):
grant members on a flow REPORT.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class ForgeShareReportRequest(BaseModel):
    """One `forge_share_report` call.

    `app_id` is already resolved by the tool (see `brief_stage_d_common.md`,
    "The app id"). `members` records pass through untouched -- the same
    `[{_id, Name, Kind: "AppRole", Role, Permission}, ...]` shape a flow's
    own member/batch accepts.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    flow_id: str
    report_id: str
    members: list[dict[str, Any]]
    app_id: str
