"""app.application.models.requests.meta.forge_capabilities_request — the DTO for
`forge_capabilities`: search the docs/capabilities/*.md capability docs, OFFLINE,
read-only.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ForgeCapabilitiesRequest(BaseModel):
    """One `forge_capabilities` call.

    `query` empty returns the full index; non-empty searches a doc's
    id/name/ui_path/status/body (case-insensitive substring).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    query: str = ""
