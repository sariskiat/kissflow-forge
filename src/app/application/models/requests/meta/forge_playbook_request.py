"""app.application.models.requests.meta.forge_playbook_request — the DTO for
`forge_playbook`: OFFLINE, read-only, no parameters.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ForgePlaybookRequest(BaseModel):
    """One `forge_playbook` call. Takes no parameters."""

    model_config = ConfigDict(frozen=True, extra="forbid")
