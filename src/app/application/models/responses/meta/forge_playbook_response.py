"""app.application.models.responses.meta.forge_playbook_response — the DTO for
`forge_playbook`'s result: today's `load_playbook()` success dict, minus `isError`
(spec G13).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ForgePlaybookResponse(BaseModel):
    """The vendored builder playbook, as `forge_playbook` returns it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    chars: int
    source: str
