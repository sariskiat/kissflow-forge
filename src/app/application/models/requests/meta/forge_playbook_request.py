"""app.application.models.requests.meta.forge_playbook_request — the DTO for
`forge_playbook`: OFFLINE, read-only, one optional closed-vocabulary name.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.domain.value_objects.kinds import PlaybookName


class ForgePlaybookRequest(BaseModel):
    """One `forge_playbook` call: which vendored skill to read. Defaults to the
    builder playbook, so a no-argument call returns what it always returned."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    skill: PlaybookName = "builder"
